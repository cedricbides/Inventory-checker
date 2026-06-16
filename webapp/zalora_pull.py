"""
zalora_pull.py — core Zalora inventory fetch (no SSE, no Flask).

Both the live SSE route (routes/zalora_routes.py) and the background
scheduler (scheduler.py) call do_pull().  The SSE route passes a
progress_cb so it can stream updates to the browser; the scheduler
passes None and gets log lines instead.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as _requests

from zalora_client import ZALORA_HOST, auth_headers, emit, get_token, mp_credentials

log = logging.getLogger(__name__)

WORKERS = 8


def do_pull(mp: dict, progress_cb=None) -> list[dict]:
    """
    Authenticate with Zalora, fetch all products + stock levels.

    Args:
        mp:           Marketplace dict from settings.json (must have type=zalora).
        progress_cb:  Optional callable(step, msg, pct).  When None, progress
                      is emitted via log.debug() instead.

    Returns:
        List of row dicts ready to be written as CSV:
          Brand, Seller SKU, Product Name, Status, MPSKU ID,
          Product Set ID, Quantity.

    Raises:
        Any requests / HTTP error that prevents the pull from completing.
    """
    brand, client_id, client_secret = mp_credentials(mp)

    def progress(step: str, msg: str, pct: int) -> None:
        emit(progress_cb, step, msg, pct, tag="zalora_pull")

    # ── Auth ──────────────────────────────────────────────────────────────────
    progress("auth", "Authenticating with Zalora API...", 5)
    token = get_token(client_id, client_secret)
    progress("auth", "Authenticated", 10)

    # ── Step 1: paginated product catalog ─────────────────────────────────────
    progress("products", "Fetching product catalog...", 12)
    sku_info_map: dict[str, dict] = {}   # ps_id → {seller_sku → {name, status, mpsku_id}}
    page, page_size = 1, 100

    while True:
        r = _requests.get(
            ZALORA_HOST + "v2/products",
            headers=auth_headers(token),
            params={"limit": page_size, "offset": (page - 1) * page_size},
            timeout=30,
        )
        if r.status_code == 401:
            token = get_token(client_id, client_secret)
            continue
        r.raise_for_status()
        body  = r.json()
        items = (
            body.get("data")
            or body.get("items")
            or (body if isinstance(body, list) else [])
        )
        if not items:
            break

        for item in items:
            ps_id = str(item.get("productSetId") or item.get("id") or "")
            if not ps_id:
                continue
            ps_skus = sku_info_map.setdefault(ps_id, {})
            for sku_item in item.get("skus") or [item]:
                seller_sku = (
                    sku_item.get("sellerSku") or sku_item.get("seller_sku") or ""
                ).strip()
                if seller_sku:
                    ps_skus[seller_sku] = {
                        "name":     item.get("name", ""),
                        "status":   sku_item.get("status", ""),
                        "mpsku_id": str(
                            sku_item.get("id") or sku_item.get("mpSkuId") or ""
                        ),
                    }

        progress(
            "products",
            f"Page {page} — {len(sku_info_map)} product sets so far...",
            min(14 + page, 30),
        )
        if len(items) < page_size:
            break
        page += 1

    ps_ids = list(sku_info_map.keys())
    progress("products", f"{len(ps_ids)} product sets found", 32)

    # ── Step 2: parallel stock fetch ──────────────────────────────────────────
    progress(
        "stock",
        f"Fetching stock for {len(ps_ids)} product sets ({WORKERS} workers)...",
        35,
    )

    def _fetch_stock(ps_id: str) -> tuple[str, list]:
        try:
            r = _requests.get(
                ZALORA_HOST + "v2/stock/product-set/" + ps_id,
                headers=auth_headers(token),
                timeout=15,
            )
            if r.status_code in (200, 201):
                body = r.json()
                entries = (
                    body
                    if isinstance(body, list)
                    else body.get("data") or body.get("stocks") or []
                )
                return ps_id, entries
        except Exception:
            pass
        return ps_id, []

    stock_map:  dict[str, list] = {}
    done_count = [0]
    tick = max(1, len(ps_ids) // 40)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_fetch_stock, pid): pid for pid in ps_ids}
        for fut in as_completed(futures):
            ps_id, result = fut.result()
            stock_map[ps_id] = result
            done_count[0] += 1
            pct = 35 + int((done_count[0] / max(len(ps_ids), 1)) * 45)
            if done_count[0] % tick == 0 or done_count[0] == len(ps_ids):
                progress(
                    "stock",
                    f"Stock: {done_count[0]} / {len(ps_ids)} fetched",
                    pct,
                )

    progress("stock", "Stock data collected", 82)

    # ── Step 3: assemble rows ─────────────────────────────────────────────────
    progress("build", "Building rows...", 85)
    rows: list[dict] = []
    for ps_id, stock_entries in stock_map.items():
        ps_skus = sku_info_map.get(ps_id, {})
        for entry in stock_entries:
            seller_sku = (
                entry.get("sellerSku") or entry.get("seller_sku") or ""
            ).strip()
            detail = ps_skus.get(seller_sku, {})
            rows.append({
                "Brand":          brand,
                "Seller SKU":     seller_sku,
                "Product Name":   detail.get("name", ""),
                "Status":         detail.get("status", ""),
                "MP SKU ID":      detail.get("mpsku_id", "") or str(entry.get("id", "")),
                "MP ITEM ID":     ps_id,
                "Quantity":       entry.get("quantity", 0),
            })

    progress("build", f"{len(rows)} SKU rows ready", 95)
    log.info("Zalora pull complete: brand=%s rows=%d", brand, len(rows))
    return rows