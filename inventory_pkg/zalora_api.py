"""
zalora_api.py

Fetches MPSKU ID and MPITEM ID for a list of seller SKUs from the Zalora API.

How it works:
  1. Bulk-fetch ALL products via GET /v2/products (paginated) — this catches
     both active and inactive listings in one go.
  2. For any SKU not found in the bulk fetch, fall back to a per-SKU lookup.

Credentials come from config.py (via credentials.py).
"""

import time
import requests

ZALORA_HOST = "https://sellercenter-api.zalora.com.ph/"

try:
    from .credentials import ZALORA_CREDENTIALS
except ImportError:
    raise ImportError(
        "credentials.py not found. "
        "Copy credentials.example.py to credentials.py and fill in your API keys."
    )

# Column name constants used by the rest of the package when storing API results
COL_MPSKU_ID  = "ZAL_MPSKU_ID"
COL_MPITEM_ID = "ZAL_MPITEM_ID"


def get_token(brand):
    """
    Fetch a Bearer token for the given brand using client credentials flow.

    Raises ValueError if no credentials exist for the brand.
    Raises RuntimeError if the API response doesn't contain an access_token.
    """
    if brand not in ZALORA_CREDENTIALS:
        raise ValueError(
            f"No Zalora credentials found for brand '{brand}'. "
            f"Available brands: {list(ZALORA_CREDENTIALS)}"
        )
    client_id     = ZALORA_CREDENTIALS[brand]["client_id"]
    client_secret = ZALORA_CREDENTIALS[brand]["client_secret"]

    resp = requests.post(
        ZALORA_HOST + "oauth/client-credentials",
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data  = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {data}")
    return token


def _headers(token):
    """Return the auth headers dict for a given bearer token."""
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def fetch_all_products(token):
    """
    Paginate through GET /v2/products and build a full product lookup dict.

    Returns { sellerSku -> { COL_MPSKU_ID: "...", COL_MPITEM_ID: "..." } }
    or None if the token expired during fetching (caller should refresh and retry).
    """
    result    = {}
    page      = 1
    page_size = 100

    print("  Fetching all products via bulk endpoint...")

    while True:
        resp = requests.get(
            ZALORA_HOST + "v2/products",
            headers=_headers(token),
            params={"limit": page_size, "offset": (page - 1) * page_size},
            timeout=30,
        )

        if resp.status_code == 401:
            return None  # signal to the caller that the token expired

        resp.raise_for_status()
        data = resp.json()

        # The API can return either a bare list or a paginated object — handle both
        items = (
            data if isinstance(data, list)
            else data.get("data", data.get("items", data.get("products", [])))
        )

        if not items:
            break

        for product in items:
            sku = str(product.get("sellerSku", "")).strip()
            if sku:
                result[sku] = {
                    COL_MPSKU_ID:  str(product.get("id", "") or ""),
                    COL_MPITEM_ID: str(product.get("productSetId", "") or ""),
                }

        print(f"    Page {page}: fetched {len(items)} products (total so far: {len(result)})")

        if len(items) < page_size:
            break  # last page reached

        page += 1
        time.sleep(0.5)

    print(f"  Bulk fetch complete: {len(result)} products found.")
    return result


def fetch_mpid_for_sku(sku, token, max_retries=3):
    """
    Per-SKU fallback: GET v2/product/seller-sku/{sku}.

    Returns (mpsku_id, mpitem_id) on success.
    Returns (None, None) if the token expired (caller should refresh).
    Returns ("", "") if the SKU genuinely doesn't exist (404).
    """
    url = ZALORA_HOST + f"v2/product/seller-sku/{sku}"

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=_headers(token), timeout=15)
            if resp.status_code == 401:
                return None, None
            if resp.status_code == 404:
                return "", ""
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("id", "") or ""), str(data.get("productSetId", "") or "")
        except Exception as e:
            print(f"    [{sku}] attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(2)

    return "", ""


def fetch_zalora_mpid_map(skus, brand, delay_ms=900):
    """
    Fetch MPSKU ID and MPITEM ID for a list of seller SKUs.

    Uses a two-step strategy:
      1. Bulk-fetch all products (fast — one paginated endpoint call)
      2. For any SKUs still missing, fall back to per-SKU lookup (slow but thorough)

    Parameters
    ----------
    skus     : list[str] — the seller SKUs to look up
    brand    : str       — used to pick the right credentials
    delay_ms : int       — wait time between per-SKU fallback requests (ms)

    Returns
    -------
    dict { sku -> { COL_MPSKU_ID: "...", COL_MPITEM_ID: "..." } }
    """
    print(f"  Fetching Zalora MPID for {len(skus)} SKUs (brand={brand})...")
    token = get_token(brand)
    print("  Token obtained.")

    bulk_map = fetch_all_products(token)

    if bulk_map is None:
        print("  Token expired during bulk fetch, refreshing...")
        token    = get_token(brand)
        bulk_map = fetch_all_products(token) or {}

    result        = {}
    still_missing = []

    for sku in skus:
        if sku in bulk_map:
            result[sku] = bulk_map[sku]
        else:
            still_missing.append(sku)

    print(f"  Matched {len(result)}/{len(skus)} SKUs from bulk fetch.")

    if still_missing:
        print(f"  Falling back to per-SKU lookup for {len(still_missing)} SKUs...")

        for i, sku in enumerate(still_missing, 1):
            mpsku_id, mpitem_id = fetch_mpid_for_sku(sku, token)

            if mpsku_id is None:
                print("    Token expired, refreshing...")
                token               = get_token(brand)
                mpsku_id, mpitem_id = fetch_mpid_for_sku(sku, token)
                if mpsku_id is None:
                    mpsku_id, mpitem_id = "", ""

            result[sku] = {
                COL_MPSKU_ID:  mpsku_id  or "",
                COL_MPITEM_ID: mpitem_id or "",
            }

            status = (
                f"MPSKU={mpsku_id}  MPITEM={mpitem_id}"
                if mpsku_id
                else "*** still no ID — not listed on Zalora"
            )
            print(f"    [{i}/{len(still_missing)}] {sku} > {status}")
            time.sleep(delay_ms / 1000)

    matched = sum(1 for v in result.values() if v[COL_MPSKU_ID])
    blank   = [s for s, v in result.items() if not v[COL_MPSKU_ID]]

    print(f"\n  Done: {matched}/{len(skus)} SKUs have MPSKU ID.")

    if blank:
        print(f"  {len(blank)} SKUs have no ID even after bulk + per-SKU lookup:")
        for s in blank:
            print(f"    - {s}  (not found on Zalora at all)")

    return result
