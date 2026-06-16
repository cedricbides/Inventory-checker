"""
shopee_reader.py — READ-ONLY Shopee Open Platform data fetchers.

All functions here are pure GET operations — no writes, no mutations.

Shopee API docs: https://open.shopee.com/documents
Credentials needed in settings.json marketplace entry (type=shopee):
  partner_id   — integer
  partner_key  — string
  shop_id      — integer
  access_token — string (OAuth2, must be refreshed periodically)

Functions
---------
  get_orders(mp, progress_cb)             → list[dict]
  get_inventory(mp, progress_cb)          → list[dict]  (item list)
"""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta

import requests as _requests

log = logging.getLogger(__name__)

SHOPEE_HOST = "https://partner.shopeemobile.com"
PAGE_SIZE   = 50   # Shopee max per page for most list endpoints


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _sign(partner_id: int, partner_key: str, path: str, ts: int, access_token: str = "", shop_id: int = 0) -> str:
    """
    Shopee HMAC-SHA256 signature.
    base_string = partner_id + path + ts + access_token + shop_id
    """
    base = f"{partner_id}{path}{ts}{access_token}{shop_id}"
    return hmac.new(
        partner_key.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _common_params(mp: dict, path: str) -> tuple[dict, dict]:
    """Return (credentials, query_params_with_auth) for a Shopee API call."""
    partner_id   = int(mp.get("partner_id", 0))
    partner_key  = mp.get("partner_key", "")
    shop_id      = int(mp.get("shop_id", 0))
    access_token = mp.get("access_token", "")
    ts           = int(time.time())
    sign         = _sign(partner_id, partner_key, path, ts, access_token, shop_id)
    creds = {
        "partner_id":   partner_id,
        "partner_key":  partner_key,
        "shop_id":      shop_id,
        "access_token": access_token,
    }
    params = {
        "partner_id":   partner_id,
        "shop_id":      shop_id,
        "access_token": access_token,
        "timestamp":    ts,
        "sign":         sign,
    }
    return creds, params


def _get(path: str, mp: dict, extra_params: dict | None = None) -> dict:
    _, params = _common_params(mp, path)
    if extra_params:
        params.update(extra_params)
    r = _requests.get(
        SHOPEE_HOST + path,
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _emit(progress_cb, step: str, msg: str, pct: int) -> None:
    if progress_cb:
        progress_cb(step, msg, pct)
    else:
        log.debug("[shopee_reader] %s — %s (%d%%)", step, msg, pct)


def _validate_credentials(mp: dict) -> None:
    required = ["partner_id", "partner_key", "shop_id", "access_token"]
    missing  = [k for k in required if not mp.get(k)]
    if missing:
        raise ValueError(
            f"Shopee marketplace is missing credentials: {', '.join(missing)}. "
            "Please configure them in Settings > Marketplaces."
        )


# ── 1. Get Orders ──────────────────────────────────────────────────────────────

def get_orders(mp: dict, progress_cb=None) -> list[dict]:
    """
    Fetch orders from Shopee Open Platform (GET /api/v2/order/get_order_list).
    READ ONLY — pulls last 15 days by default (Shopee max window per call = 15 days).

    Returns flat rows suitable for CSV export.
    """
    brand = (mp.get("brand") or "").strip()
    _validate_credentials(mp)

    _emit(progress_cb, "auth", "Validating Shopee credentials…", 5)

    PATH_LIST   = "/api/v2/order/get_order_list"
    PATH_DETAIL = "/api/v2/order/get_order_detail"

    # Shopee time range: Unix timestamps, max 15 days per window
    time_to   = int(time.time())
    time_from = time_to - (15 * 24 * 3600)

    _emit(progress_cb, "fetch", "Fetching order list…", 15)

    # ── Step 1: paginate order numbers ────────────────────────────────────────
    all_order_sns: list[str] = []
    cursor = ""

    while True:
        params = {
            "time_range_field": "create_time",
            "time_from":        time_from,
            "time_to":          time_to,
            "page_size":        PAGE_SIZE,
            "order_status":     "ALL",
        }
        if cursor:
            params["cursor"] = cursor

        body = _get(PATH_LIST, mp, params)
        resp = body.get("response") or {}
        orders_raw = resp.get("order_list") or []

        all_order_sns.extend(o["order_sn"] for o in orders_raw if o.get("order_sn"))

        if not resp.get("more", False):
            break
        cursor = resp.get("next_cursor", "")
        if not cursor:
            break

        _emit(progress_cb, "fetch", f"{len(all_order_sns)} orders found so far…", min(20 + len(all_order_sns) // 10, 50))

    _emit(progress_cb, "fetch", f"{len(all_order_sns)} orders — fetching details…", 55)

    # ── Step 2: batch detail fetch (max 50 per call) ──────────────────────────
    rows: list[dict] = []
    batch_size = 50
    batches    = [all_order_sns[i:i + batch_size] for i in range(0, len(all_order_sns), batch_size)]

    for idx, batch in enumerate(batches):
        body = _get(PATH_DETAIL, mp, {
            "order_sn_list": ",".join(batch),
            "response_optional_fields": "buyer_username,item_list,payment_method,total_amount",
        })
        order_list = (body.get("response") or {}).get("order_list") or []

        for o in order_list:
            for item in (o.get("item_list") or [{}]):
                rows.append({
                    "Brand":            brand,
                    "Order SN":         o.get("order_sn", ""),
                    "Order Status":     o.get("order_status", ""),
                    "Payment Method":   o.get("payment_method", ""),
                    "Total Amount":     o.get("total_amount", ""),
                    "Currency":         o.get("currency", "PHP"),
                    "Create Time":      datetime.fromtimestamp(o.get("create_time", 0)).strftime("%Y-%m-%d %H:%M") if o.get("create_time") else "",
                    "Update Time":      datetime.fromtimestamp(o.get("update_time", 0)).strftime("%Y-%m-%d %H:%M") if o.get("update_time") else "",
                    "Buyer Username":   o.get("buyer_username", ""),
                    "Shipping Carrier": o.get("shipping_carrier", ""),
                    "Item ID":          item.get("item_id", ""),
                    "Item Name":        item.get("item_name", ""),
                    "Model SKU":        item.get("model_sku") or item.get("item_sku", ""),
                    "Qty":              item.get("model_quantity_purchased") or item.get("quantity_purchased", ""),
                    "Item Price":       item.get("model_discounted_price") or item.get("item_price", ""),
                })

        pct = 55 + int(((idx + 1) / max(len(batches), 1)) * 35)
        _emit(progress_cb, "detail", f"Batch {idx+1}/{len(batches)} done", pct)

    _emit(progress_cb, "done", f"{len(rows)} order line rows ready", 100)
    log.info("Shopee orders: brand=%s rows=%d", brand, len(rows))
    return rows


# ── 2. Inventory (Item List) ───────────────────────────────────────────────────

def get_inventory(mp: dict, progress_cb=None) -> list[dict]:
    """
    Fetch item list + stock from Shopee (GET /api/v2/product/get_item_list).
    READ ONLY.
    """
    brand = (mp.get("brand") or "").strip()
    _validate_credentials(mp)

    _emit(progress_cb, "auth", "Validating Shopee credentials…", 5)

    PATH_LIST   = "/api/v2/product/get_item_list"
    PATH_DETAIL = "/api/v2/product/get_item_base_info"
    PATH_STOCK  = "/api/v2/product/get_model_list"

    _emit(progress_cb, "fetch", "Fetching item list…", 15)

    all_item_ids: list[int] = []
    offset = 0

    while True:
        body = _get(PATH_LIST, mp, {
            "offset":      offset,
            "page_size":   PAGE_SIZE,
            "item_status": "NORMAL",
        })
        resp  = body.get("response") or {}
        items = resp.get("item", [])
        all_item_ids.extend(i["item_id"] for i in items if i.get("item_id"))

        if not resp.get("has_next_page", False):
            break
        offset += PAGE_SIZE
        _emit(progress_cb, "fetch", f"{len(all_item_ids)} items found…", min(15 + len(all_item_ids) // 5, 45))

    _emit(progress_cb, "fetch", f"{len(all_item_ids)} items — fetching stock…", 50)

    rows: list[dict] = []
    batch_size = 50

    for idx, batch_start in enumerate(range(0, len(all_item_ids), batch_size)):
        batch = all_item_ids[batch_start:batch_start + batch_size]

        # Base info
        base_resp = _get(PATH_DETAIL, mp, {
            "item_id_list": ",".join(str(i) for i in batch),
        })
        item_map = {
            i["item_id"]: i
            for i in (base_resp.get("response") or {}).get("item_list", [])
        }

        # Stock per item
        for item_id in batch:
            stock_resp = _get(PATH_STOCK, mp, {"item_id": item_id})
            models     = (stock_resp.get("response") or {}).get("model", [])
            item_info  = item_map.get(item_id, {})

            if not models:
                models = [{"model_id": "", "model_sku": "", "stock_info_v2": {}}]

            for model in models:
                stock_info = model.get("stock_info_v2") or {}
                seller_stock = (stock_info.get("seller_stock") or [{}])[0]
                rows.append({
                    "Brand":        brand,
                    "Item ID":      item_id,
                    "Item Name":    item_info.get("item_name", ""),
                    "Item Status":  item_info.get("item_status", ""),
                    "Model ID":     model.get("model_id", ""),
                    "Model SKU":    model.get("model_sku") or item_info.get("item_sku", ""),
                    "Current Stock":seller_stock.get("stock", 0),
                    "Reserved":     stock_info.get("shopee_stock", [{}])[0].get("stock", 0) if stock_info.get("shopee_stock") else 0,
                    "Currency":     item_info.get("currency", "PHP"),
                })

        pct = 50 + int(((idx + 1) / max(len(all_item_ids) // batch_size + 1, 1)) * 40)
        _emit(progress_cb, "stock", f"Stock: {min((idx+1)*batch_size, len(all_item_ids))}/{len(all_item_ids)}", pct)

    _emit(progress_cb, "done", f"{len(rows)} SKU rows ready", 100)
    log.info("Shopee inventory: brand=%s rows=%d", brand, len(rows))
    return rows
