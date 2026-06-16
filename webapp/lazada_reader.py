"""
lazada_reader.py — READ-ONLY Lazada Open Platform data fetchers.

All functions here are pure GET operations — no writes, no mutations.

Lazada API docs: https://open.lazada.com/doc/api.htm
Credentials needed in settings.json marketplace entry (type=lazada):
  app_key      — string
  app_secret   — string
  access_token — string (OAuth2)
  region       — 'PH' | 'SG' | 'MY' | 'TH' | 'VN' | 'ID'  (default PH)

Functions
---------
  get_orders(mp, progress_cb)    → list[dict]
  get_inventory(mp, progress_cb) → list[dict]
"""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests as _requests

log = logging.getLogger(__name__)

LAZADA_HOSTS = {
    "PH": "https://api.lazada.com.ph/rest",
    "SG": "https://api.lazada.sg/rest",
    "MY": "https://api.lazada.com.my/rest",
    "TH": "https://api.lazada.co.th/rest",
    "VN": "https://api.lazada.vn/rest",
    "ID": "https://api.lazada.co.id/rest",
}
PAGE_SIZE = 50


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_host(mp: dict) -> str:
    region = (mp.get("region") or "PH").upper()
    return LAZADA_HOSTS.get(region, LAZADA_HOSTS["PH"])


def _sign(app_secret: str, path: str, params: dict) -> str:
    """
    Lazada HMAC-SHA256 signature.
    Sorted param string: app_secret + /path + key1val1key2val2…
    """
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    base_string   = path + sorted_params
    return hmac.new(
        app_secret.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()


def _call(mp: dict, path: str, extra: dict | None = None) -> dict:
    app_key      = mp.get("app_key", "")
    app_secret   = mp.get("app_secret", "")
    access_token = mp.get("access_token", "")
    ts           = str(int(time.time() * 1000))  # milliseconds

    params: dict = {
        "app_key":      app_key,
        "access_token": access_token,
        "timestamp":    ts,
        "sign_method":  "sha256",
    }
    if extra:
        params.update(extra)

    params["sign"] = _sign(app_secret, path, params)

    r = _requests.get(
        _get_host(mp) + path,
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()

    if body.get("code") not in (None, "", "0", 0, "200"):
        raise RuntimeError(f"Lazada API error {body.get('code')}: {body.get('message', 'unknown')}")

    return body


def _emit(progress_cb, step: str, msg: str, pct: int) -> None:
    if progress_cb:
        progress_cb(step, msg, pct)
    else:
        log.debug("[lazada_reader] %s — %s (%d%%)", step, msg, pct)


def _validate_credentials(mp: dict) -> None:
    required = ["app_key", "app_secret", "access_token"]
    missing  = [k for k in required if not mp.get(k)]
    if missing:
        raise ValueError(
            f"Lazada marketplace is missing credentials: {', '.join(missing)}. "
            "Please configure them in Settings > Marketplaces."
        )


# ── 1. Get Orders ──────────────────────────────────────────────────────────────

def get_orders(mp: dict, progress_cb=None) -> list[dict]:
    """
    Fetch orders from Lazada Open Platform (GET /orders/get).
    READ ONLY — pulls last 30 days by default.

    Returns flat rows suitable for CSV export.
    """
    brand = (mp.get("brand") or "").strip()
    _validate_credentials(mp)

    _emit(progress_cb, "auth", "Validating Lazada credentials…", 5)

    date_to   = datetime.now()
    date_from = date_to - timedelta(days=30)
    fmt       = "%Y-%m-%d %H:%M:%S"

    _emit(progress_cb, "fetch", "Fetching orders…", 15)

    all_orders: list[dict] = []
    offset = 0

    while True:
        body = _call(mp, "/orders/get", {
            "created_after":  date_from.strftime(fmt),
            "created_before": date_to.strftime(fmt),
            "status":         "unpaid,pending,ready_to_ship,delivered,returned,shipped,failed,canceled",
            "limit":          PAGE_SIZE,
            "offset":         offset,
            "sort_by":        "created_at",
            "sort_direction": "DESC",
        })
        orders = (body.get("data") or {}).get("orders", [])
        all_orders.extend(orders)

        count_total = (body.get("data") or {}).get("count", len(all_orders))
        _emit(progress_cb, "fetch", f"{len(all_orders)} / {count_total} orders…", min(15 + len(all_orders) // 5, 60))

        if len(orders) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    _emit(progress_cb, "fetch", f"{len(all_orders)} orders — fetching items…", 65)

    # ── Flatten order items ────────────────────────────────────────────────────
    rows: list[dict] = []
    for o in all_orders:
        order_id = o.get("order_id", "")
        # Fetch order items
        try:
            items_body = _call(mp, "/order/items/get", {"order_id": order_id})
            items      = items_body.get("data", [])
        except Exception as exc:
            log.debug("Could not fetch items for order %s: %s", order_id, exc)
            items = [{}]

        for item in items:
            rows.append({
                "Brand":          brand,
                "Order ID":       order_id,
                "Order Number":   o.get("order_number", ""),
                "Order Status":   o.get("status", ""),
                "Payment Method": o.get("payment_method", ""),
                "Price":          o.get("price", ""),
                "Currency":       o.get("currency", "PHP"),
                "Created At":     o.get("created_at", ""),
                "Updated At":     o.get("updated_at", ""),
                "Customer Name":  o.get("customer_first_name", "") + " " + o.get("customer_last_name", ""),
                "Item ID":        item.get("order_item_id", ""),
                "SKU":            item.get("sku", ""),
                "Product Name":   item.get("name", ""),
                "Qty":            item.get("qty", ""),
                "Item Price":     item.get("item_price", ""),
                "Paid Price":     item.get("paid_price", ""),
                "Ship By Date":   item.get("ship_by_date", ""),
            })

    _emit(progress_cb, "done", f"{len(rows)} order line rows ready", 100)
    log.info("Lazada orders: brand=%s rows=%d", brand, len(rows))
    return rows


# ── 2. Inventory (Product list + stock) ───────────────────────────────────────

def get_inventory(mp: dict, progress_cb=None) -> list[dict]:
    """
    Fetch product list + stock from Lazada (GET /products/get).
    READ ONLY.
    """
    brand = (mp.get("brand") or "").strip()
    _validate_credentials(mp)

    _emit(progress_cb, "auth", "Validating Lazada credentials…", 5)
    _emit(progress_cb, "fetch", "Fetching product list…", 15)

    all_products: list[dict] = []
    offset = 0

    while True:
        body = _call(mp, "/products/get", {
            "filter":  "all",
            "limit":   PAGE_SIZE,
            "offset":  offset,
        })
        products = (body.get("data") or {}).get("products", [])
        all_products.extend(products)

        total = (body.get("data") or {}).get("total_products", len(all_products))
        _emit(progress_cb, "fetch", f"{len(all_products)} / {total} products…", min(15 + int(len(all_products) / max(total, 1) * 60), 75))

        if len(products) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    _emit(progress_cb, "build", "Building rows…", 80)

    rows: list[dict] = []
    for product in all_products:
        product_id   = product.get("item_id", "")
        product_name = (product.get("attributes") or {}).get("name", "")

        for sku in (product.get("skus") or []):
            rows.append({
                "Brand":          brand,
                "Item ID":        product_id,
                "Product Name":   product_name,
                "Seller SKU":     sku.get("SellerSku", ""),
                "Shop SKU":       sku.get("ShopSku", ""),
                "Status":         sku.get("Status", ""),
                "Available":      sku.get("Available", 0),
                "Quantity":       sku.get("quantity", 0),
                "Price":          sku.get("price", ""),
                "Special Price":  sku.get("special_price", ""),
                "Currency":       "PHP",
            })

    _emit(progress_cb, "done", f"{len(rows)} SKU rows ready", 100)
    log.info("Lazada inventory: brand=%s rows=%d", brand, len(rows))
    return rows
