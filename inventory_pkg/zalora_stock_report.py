"""
zalora_stock_report.py

Fetches SellerSKU, Stock, ZAL_MPSKU_ID, ZAL_MPITEM_ID, and Status from the
Zalora API and saves a CSV to the Zalora/ folder next to inventory_pkg/.

Usage:
  python -m inventory_pkg.zalora_stock_report
  python -m inventory_pkg.zalora_stock_report --brand Lacoste

How it works (three steps):
  1. Bulk-fetch all products via GET /v2/products (paginated).
     Each item gives: sellerSku, id (MPSKU_ID), productSetId (MPITEM_ID), status.
  2. Collect the unique productSetIds from step 1.
     Fetch stock for each via GET /v2/stock/product-set/{id} in parallel.
  3. Join: for every (sellerSku, quantity) in the stock results, look up
     MPSKU_ID and Status from the step 1 map.
"""

import argparse
import csv
import os
import sys
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter

try:
    from inventory_pkg.credentials import ZALORA_CREDENTIALS
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from inventory_pkg.credentials import ZALORA_CREDENTIALS

ZALORA_HOST = "https://sellercenter-api.zalora.com.ph/"
WORKERS     = 30
PAGE_SIZE   = 100

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_OUT = os.path.join(WORKING_DIR, "Zalora")

CSV_FIELDS = ["SellerSKU", "Stock", "ZAL_MPSKU_ID", "ZAL_MPITEM_ID", "Status"]

SESSION    = None
TOKEN_LOCK = threading.Lock()


def make_session():
    """Create a requests Session with connection pooling sized for WORKERS threads."""
    s = requests.Session()
    a = HTTPAdapter(
        pool_connections=WORKERS + 5,
        pool_maxsize=WORKERS + 5,
        max_retries=2,
    )
    s.mount("https://", a)
    return s


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def get_token(brand):
    """
    Get a Bearer token for the given brand using client credentials.

    Works with both dict credentials (new format) and tuple credentials
    (legacy format from older credentials.py files).
    """
    creds = ZALORA_CREDENTIALS[brand]
    if isinstance(creds, dict):
        cid, csec = creds["client_id"], creds["client_secret"]
    else:
        cid, csec = creds

    r = SESSION.post(
        ZALORA_HOST + "oauth/client-credentials",
        data={
            "grant_type":    "client_credentials",
            "client_id":     cid,
            "client_secret": csec,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _extract_status(item):
    """
    Pull the listing status out of a product API item.

    Zalora uses different field names across API versions, so we check
    several possibilities. Boolean fields (like 'active') get converted
    to 'Active' / 'Inactive' strings.
    """
    for key in ("status", "productStatus", "active", "state", "listingStatus"):
        val = item.get(key)
        if val is not None:
            if isinstance(val, bool):
                return "Active" if val else "Inactive"
            return str(val).strip().title()
    return ""


def fetch_bulk_products(token, brand):
    """
    Paginate GET /v2/products and return a lookup keyed by sellerSku.

    Returns { sellerSku -> {"ZAL_MPSKU_ID": str, "ZAL_MPITEM_ID": str, "Status": str} }
    or None if the token expired (caller must refresh and retry).
    """
    result = {}
    page   = 1

    print("  [Step 1] Bulk-fetching all products via GET /v2/products ...")

    while True:
        try:
            resp = SESSION.get(
                ZALORA_HOST + "v2/products",
                headers=_auth_headers(token),
                params={"limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
                timeout=30,
            )
        except Exception as e:
            print(f"    Page {page} request failed: {e} — retrying once...")
            time.sleep(2)
            try:
                resp = SESSION.get(
                    ZALORA_HOST + "v2/products",
                    headers=_auth_headers(token),
                    params={"limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
                    timeout=30,
                )
            except Exception as e2:
                print(f"    Page {page} retry also failed: {e2} — stopping bulk fetch.")
                break

        if resp.status_code == 401:
            return None  # token expired — let the caller handle it

        if not resp.ok:
            print(f"    Page {page} returned HTTP {resp.status_code} — stopping.")
            break

        data  = resp.json()
        items = (
            data if isinstance(data, list)
            else data.get("data") or data.get("items") or data.get("products") or []
        )

        if not items:
            break

        for product in items:
            sku = str(product.get("sellerSku", "")).strip()
            if not sku:
                continue
            result[sku] = {
                "ZAL_MPSKU_ID":  str(product.get("id", "") or "").strip(),
                "ZAL_MPITEM_ID": str(product.get("productSetId", "") or "").strip(),
                "Status":        _extract_status(product),
            }

        print(f"    Page {page}: {len(items)} items  |  total unique SKUs: {len(result)}")

        if len(items) < PAGE_SIZE:
            break  # last page

        page += 1
        time.sleep(0.3)

    print(f"  Bulk fetch done: {len(result)} unique SKUs found.")
    return result


def _fetch_stock_for_ps(ps_id, token):
    """
    Fetch stock for a single productSetId.
    Returns (ps_id, items_list) or (ps_id, None) if the token expired.
    """
    try:
        r = SESSION.get(
            ZALORA_HOST + f"v2/stock/product-set/{ps_id}",
            headers=_auth_headers(token),
            timeout=15,
        )
        if r.status_code == 401:
            return ps_id, None
        if not r.ok:
            return ps_id, []
        data  = r.json()
        items = data if isinstance(data, list) else [data]
        return ps_id, items
    except Exception:
        return ps_id, []


def fetch_stock_for_all_sets(ps_ids, token, brand):
    """
    Fetch stock for every productSetId in parallel using a thread pool.

    If a request comes back with a 401, refreshes the token and retries
    that single request once before giving up on it.

    Returns (stock_map, updated_token).
    stock_map is { ps_id -> [{sellerSku, quantity, ...}] }.
    """
    stock_map    = {}
    done, total  = 0, len(ps_ids)

    print(f"  [Step 2] Fetching stock for {total} product-sets ({WORKERS} workers)...")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_fetch_stock_for_ps, pid, token): pid for pid in ps_ids}

        for future in as_completed(futures):
            ps_id, result = future.result()
            done += 1

            if result is None:
                with TOKEN_LOCK:
                    token = get_token(brand)
                _, result = _fetch_stock_for_ps(ps_id, token)
                result = result or []

            stock_map[ps_id] = result

            if done % 100 == 0 or done == total:
                print(f"  {done}/{total} stock calls done", end="\r")

    print()
    return stock_map, token


def build_rows(stock_map, sku_info_map):
    """
    Join the stock data with the bulk product info to build the final CSV rows.

    sku_info_map : { sellerSku -> {ZAL_MPSKU_ID, ZAL_MPITEM_ID, Status} }
    stock_map    : { ps_id -> [{sellerSku, quantity, ...}] }
    """
    rows = []
    for ps_id, entries in stock_map.items():
        for entry in entries:
            seller_sku = str(entry.get("sellerSku", "")).strip()
            info = sku_info_map.get(seller_sku, {})
            rows.append({
                "SellerSKU":     seller_sku,
                "Stock":         entry.get("quantity", 0),
                "ZAL_MPSKU_ID":  info.get("ZAL_MPSKU_ID", ""),
                "ZAL_MPITEM_ID": info.get("ZAL_MPITEM_ID", ps_id),
                "Status":        info.get("Status", ""),
            })
    return rows


def run_for_brand(brand, out_dir):
    """
    Run the full stock report for a single brand and write a CSV file.

    Returns the output filepath on success, or None if no data was found.
    """
    print(f"\n{'=' * 50}\n  {brand}\n{'=' * 50}")

    print("  Authenticating...")
    token = get_token(brand)
    print("  Token OK.")

    t0 = time.time()

    sku_info_map = fetch_bulk_products(token, brand)
    if sku_info_map is None:
        print("  Token expired during bulk fetch — refreshing...")
        token        = get_token(brand)
        sku_info_map = fetch_bulk_products(token, brand) or {}

    if not sku_info_map:
        print("  No products returned from bulk fetch — skipping.")
        return None

    ps_ids = sorted({v["ZAL_MPITEM_ID"] for v in sku_info_map.values() if v["ZAL_MPITEM_ID"]})
    print(f"  Unique product-sets: {len(ps_ids)}")

    stock_map, token = fetch_stock_for_all_sets(ps_ids, token, brand)

    rows = build_rows(stock_map, sku_info_map)

    if not rows:
        print("  No stock rows returned.")
        return None

    blank_mpsku  = sum(1 for r in rows if not r["ZAL_MPSKU_ID"])
    blank_status = sum(1 for r in rows if not r["Status"])
    status_counts = {}
    for r in rows:
        s = r["Status"] or "(blank)"
        status_counts[s] = status_counts.get(s, 0) + 1

    print(f"\n  Total rows      : {len(rows)}")
    print(f"  Blank MPSKU_ID  : {blank_mpsku}")
    print(f"  Blank Status    : {blank_status}")
    print("  Status breakdown:")
    for s, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"    {s:20s}: {count}")

    os.makedirs(out_dir, exist_ok=True)
    stamp    = datetime.now().strftime("%Y-%m-%d_%H-%M")
    safe     = brand.replace(" ", "_").replace("/", "-")
    filepath = os.path.join(out_dir, f"ZaloraStock_{safe}_{stamp}.csv")

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  Saved : {filepath}")
    print(f"  Total : {time.time() - t0:.1f}s")
    return filepath


def main():
    global SESSION
    SESSION = make_session()

    parser = argparse.ArgumentParser(
        description="Fetch Zalora stock report with MPSKU_ID, MPITEM_ID, and Status."
    )
    parser.add_argument(
        "--brand",
        action="append",
        dest="brands",
        metavar="BRAND",
        help="Brand name (can be repeated). Default: all brands in credentials.",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"Output directory. Default: {DEFAULT_OUT}",
    )
    args = parser.parse_args()

    brands = args.brands or list(ZALORA_CREDENTIALS.keys())
    print(f"Brands  : {', '.join(brands)}")
    print(f"Workers : {WORKERS}")
    print(f"Output  : {args.out}")

    for brand in brands:
        if brand not in ZALORA_CREDENTIALS:
            print(f"\n  [SKIP] No credentials for '{brand}'")
            continue
        run_for_brand(brand, args.out)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
