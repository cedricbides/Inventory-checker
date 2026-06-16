"""
zalora_reader.py — read-only Zalora data fetchers (orders, payouts, QC).

Each function accepts a marketplace dict from settings.json and an optional
progress callback, and returns row dicts ready for CSV export.
"""

import logging
from datetime import datetime, timedelta

from zalora_client import (
    ZALORA_HOST,
    emit,
    get_token,
    mp_credentials,
    paginate,
)

log = logging.getLogger(__name__)


def get_autoship_orders(mp: dict, progress_cb=None) -> list[dict]:
    """Fetch autoship orders (GET /v2/orders, autoship filter)."""
    brand, client_id, client_secret = mp_credentials(mp)

    emit(progress_cb, "auth", "Authenticating with Zalora…", 5)
    token = get_token(client_id, client_secret)
    emit(progress_cb, "auth", "Authenticated", 10)

    emit(progress_cb, "fetch", "Fetching autoship orders…", 15)
    items = paginate(
        ZALORA_HOST + "v2/orders",
        token,
        params={"order_type": "autoship"},
    )
    emit(progress_cb, "fetch", f"{len(items)} orders fetched", 80)

    emit(progress_cb, "build", "Building rows…", 85)
    rows = []
    for o in items:
        rows.append({
            "Brand":            brand,
            "Order ID":         o.get("orderId") or o.get("id", ""),
            "Order Number":     o.get("orderNumber") or o.get("order_number", ""),
            "Status":           o.get("status", ""),
            "Autoship Type":    o.get("autoshipType") or o.get("order_type", ""),
            "Created At":       o.get("createdAt") or o.get("created_at", ""),
            "Customer Name":    o.get("customerName") or o.get("customer_name", ""),
            "Total":            o.get("totalAmount") or o.get("total", ""),
            "Currency":         o.get("currency", "PHP"),
            "Items Count":      len(o.get("items") or []),
        })

    emit(progress_cb, "done", f"{len(rows)} autoship orders ready", 100)
    log.info("Zalora autoship orders: brand=%s rows=%d", brand, len(rows))
    return rows


def get_order_reco(mp: dict, progress_cb=None) -> list[dict]:
    """Fetch order reconciliation data; falls back to /v2/orders if needed."""
    brand, client_id, client_secret = mp_credentials(mp)

    emit(progress_cb, "auth", "Authenticating with Zalora…", 5)
    token = get_token(client_id, client_secret)
    emit(progress_cb, "auth", "Authenticated", 10)
    emit(progress_cb, "fetch", "Fetching order reconciliation…", 15)

    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    try:
        items = paginate(
            ZALORA_HOST + "v2/orders/reconciliation",
            token,
            params={"date_from": date_from, "date_to": date_to},
        )
        used = "reconciliation"
    except Exception:
        log.debug("Reconciliation endpoint not available, falling back to /v2/orders")
        used = "orders_fallback"
        items = paginate(
            ZALORA_HOST + "v2/orders",
            token,
            params={"created_after": date_from, "created_before": date_to},
        )

    emit(progress_cb, "fetch", f"{len(items)} records fetched ({used})", 80)
    emit(progress_cb, "build", "Building rows…", 85)

    rows = []
    for o in items:
        rows.append({
            "Brand":          brand,
            "Order ID":       o.get("orderId") or o.get("id", ""),
            "Order Number":   o.get("orderNumber") or o.get("order_number", ""),
            "Status":         o.get("status", ""),
            "Payment Method": o.get("paymentMethod") or o.get("payment_method", ""),
            "Created At":     o.get("createdAt") or o.get("created_at", ""),
            "Updated At":     o.get("updatedAt") or o.get("updated_at", ""),
            "Total Amount":   o.get("totalAmount") or o.get("total", ""),
            "Currency":       o.get("currency", "PHP"),
            "Source":         used,
        })

    emit(progress_cb, "done", f"{len(rows)} reconciliation rows ready", 100)
    log.info("Zalora order reco: brand=%s rows=%d source=%s", brand, len(rows), used)
    return rows


def get_payout(mp: dict, progress_cb=None) -> list[dict]:
    """Fetch payout/finance data (GET /v2/finance/payouts or statements)."""
    brand, client_id, client_secret = mp_credentials(mp)

    emit(progress_cb, "auth", "Authenticating with Zalora…", 5)
    token = get_token(client_id, client_secret)
    emit(progress_cb, "auth", "Authenticated", 10)
    emit(progress_cb, "fetch", "Fetching payout records…", 15)

    date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    try:
        items = paginate(
            ZALORA_HOST + "v2/finance/payouts",
            token,
            params={"date_from": date_from, "date_to": date_to},
        )
        endpoint_used = "finance/payouts"
    except Exception:
        log.debug("finance/payouts not available, trying finance/statements")
        try:
            items = paginate(
                ZALORA_HOST + "v2/finance/statements",
                token,
                params={"date_from": date_from, "date_to": date_to},
            )
            endpoint_used = "finance/statements"
        except Exception:
            log.warning("No payout endpoint available for this account")
            items = []
            endpoint_used = "none"

    emit(progress_cb, "fetch", f"{len(items)} payout records fetched", 80)
    emit(progress_cb, "build", "Building rows…", 85)

    rows = []
    for p in items:
        rows.append({
            "Brand":        brand,
            "Payout ID":    p.get("payoutId") or p.get("id", ""),
            "Statement ID": p.get("statementId") or p.get("statement_id", ""),
            "Period From":  p.get("periodFrom") or p.get("period_from") or date_from,
            "Period To":    p.get("periodTo") or p.get("period_to") or date_to,
            "Gross Sales":  p.get("grossSales") or p.get("gross_sales", 0),
            "Net Payout":   p.get("netPayout") or p.get("net_payout") or p.get("amount", 0),
            "Currency":     p.get("currency", "PHP"),
            "Status":       p.get("status", ""),
            "Paid At":      p.get("paidAt") or p.get("paid_at") or p.get("created_at", ""),
            "Source":       endpoint_used,
        })

    emit(progress_cb, "done", f"{len(rows)} payout rows ready", 100)
    log.info("Zalora payouts: brand=%s rows=%d endpoint=%s", brand, len(rows), endpoint_used)
    return rows


def get_qc_status(mp: dict, progress_cb=None) -> list[dict]:
    """Fetch product QC status (GET /v2/products/qc-status)."""
    brand, client_id, client_secret = mp_credentials(mp)

    emit(progress_cb, "auth", "Authenticating with Zalora…", 5)
    token = get_token(client_id, client_secret)
    emit(progress_cb, "auth", "Authenticated", 10)
    emit(progress_cb, "fetch", "Fetching QC status list…", 15)

    try:
        items = paginate(ZALORA_HOST + "v2/products/qc-status", token)
    except Exception:
        log.debug("qc-status endpoint not available, trying /v2/products")
        items = paginate(ZALORA_HOST + "v2/products", token)

    emit(progress_cb, "fetch", f"{len(items)} QC records fetched", 80)
    emit(progress_cb, "build", "Building rows…", 85)

    rows = []
    for item in items:
        skus = item.get("skus") or [item]
        for sku in skus:
            rows.append({
                "Brand":          brand,
                "Product Set ID": str(item.get("productSetId") or item.get("id", "")),
                "Product Name":   item.get("name") or item.get("product_name", ""),
                "Seller SKU":     (sku.get("sellerSku") or sku.get("seller_sku", "")).strip(),
                "MP SKU ID":      str(sku.get("id") or sku.get("mpSkuId", "")),
                "QC Status":      (
                    sku.get("qcStatus") or sku.get("qc_status")
                    or item.get("qcStatus") or item.get("qc_status", "")
                ),
                "QC Message":     (
                    sku.get("qcMessage") or sku.get("qc_message")
                    or item.get("qcMessage") or item.get("qc_message", "")
                ),
                "Product Status": sku.get("status") or item.get("status", ""),
                "Updated At":     (
                    sku.get("updatedAt") or sku.get("updated_at")
                    or item.get("updatedAt") or item.get("updated_at", "")
                ),
            })

    emit(progress_cb, "done", f"{len(rows)} QC rows ready", 100)
    log.info("Zalora QC status: brand=%s rows=%d", brand, len(rows))
    return rows
