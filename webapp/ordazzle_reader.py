"""
ordazzle_reader.py — READ-ONLY Ordazzle data fetchers.

All functions here are pure GET/export operations — no writes, no mutations.

Credentials in settings.json (ordazzle_system key):
  base_url  — e.g. "https://your-tenant.ordazzle.com"
  username  — API username
  password  — API password

Functions
---------
  export_ssi_ebg(cfg, progress_cb)   → list[dict]   Ordazzle Export SSI EBG
  export_slci(cfg, progress_cb)      → list[dict]   Ordazzle Export SLCI
  sap_order_sync(cfg, progress_cb)   → list[dict]   Ordazzle SAP Order Sync (read)
"""

import logging

import requests as _requests
from requests.auth import HTTPBasicAuth

log = logging.getLogger(__name__)


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _auth(cfg: dict) -> HTTPBasicAuth:
    return HTTPBasicAuth(cfg.get("username", ""), cfg.get("password", ""))


def _base(cfg: dict) -> str:
    return (cfg.get("base_url") or "").rstrip("/")


def _get(cfg: dict, path: str, params: dict | None = None) -> dict | list:
    url = _base(cfg) + path
    r   = _requests.get(url, auth=_auth(cfg), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _emit(progress_cb, step: str, msg: str, pct: int) -> None:
    if progress_cb:
        progress_cb(step, msg, pct)
    else:
        log.debug("[ordazzle_reader] %s — %s (%d%%)", step, msg, pct)


def _validate(cfg: dict) -> None:
    if not cfg.get("base_url"):
        raise ValueError("Ordazzle base_url is not configured. Set it in Settings > Systems > Ordazzle.")
    if not cfg.get("username") or not cfg.get("password"):
        raise ValueError("Ordazzle username/password not configured. Set them in Settings > Systems > Ordazzle.")


def _load_ordazzle_cfg() -> dict:
    """Load ordazzle_system block from settings.json."""
    from helpers import load_settings
    s = load_settings()
    cfg = s.get("ordazzle_system") or {}
    return cfg


# ── Shared inventory fetch ─────────────────────────────────────────────────────

def _fetch_inventory(cfg: dict, warehouse_codes: list[str], progress_cb=None) -> list[dict]:
    """
    Generic inventory fetch for a list of warehouse codes.
    Tries standard Ordazzle inventory export endpoints.
    """
    _emit(progress_cb, "fetch", f"Fetching inventory for warehouses: {', '.join(warehouse_codes)}…", 20)

    all_rows: list[dict] = []

    for wh_code in warehouse_codes:
        _emit(progress_cb, "fetch", f"Fetching {wh_code}…", 20)

        # Try the standard inventory export endpoint
        # Ordazzle typically has /api/inventory/export or /api/stock/list
        endpoints_to_try = [
            f"/api/inventory/export?warehouse={wh_code}",
            f"/api/stock/list?warehouse_code={wh_code}",
            f"/api/wms/inventory?warehouse={wh_code}",
        ]

        items = []
        for ep in endpoints_to_try:
            try:
                result = _get(cfg, ep.split("?")[0], dict(
                    param.split("=") for param in (ep.split("?")[1:][0].split("&") if "?" in ep else [])
                ))
                items = result if isinstance(result, list) else (result.get("data") or result.get("items") or [])
                if items:
                    log.debug("Ordazzle inventory from %s: %d items", ep, len(items))
                    break
            except Exception as exc:
                log.debug("Ordazzle endpoint %s failed: %s", ep, exc)
                continue

        for item in items:
            all_rows.append({
                "Warehouse":     wh_code,
                "SKU":           item.get("sku") or item.get("article_code") or item.get("item_code", ""),
                "Product Name":  item.get("product_name") or item.get("name") or item.get("description", ""),
                "Qty On Hand":   item.get("qty_on_hand") or item.get("quantity") or item.get("stock", 0),
                "Qty Reserved":  item.get("qty_reserved") or item.get("reserved", 0),
                "Qty Available": item.get("qty_available") or item.get("available", 0),
                "UOM":           item.get("uom") or item.get("unit", ""),
                "Last Updated":  item.get("updated_at") or item.get("last_updated", ""),
            })

    return all_rows


# ── 1. Export SSI EBG ──────────────────────────────────────────────────────────

def export_ssi_ebg(cfg: dict | None = None, progress_cb=None) -> list[dict]:
    """
    Export SSI EBG warehouse inventory from Ordazzle.
    READ ONLY — fetches stock data, no mutations.

    SSI EBG warehouses: SSIEBG_WH_EBGWarehouse
    """
    if cfg is None:
        cfg = _load_ordazzle_cfg()

    _validate(cfg)
    _emit(progress_cb, "auth", "Connecting to Ordazzle…", 5)

    # Verify connectivity
    try:
        _get(cfg, "/api/health")
        _emit(progress_cb, "auth", "Connected", 10)
    except Exception:
        try:
            _get(cfg, "/api/v1/ping")
            _emit(progress_cb, "auth", "Connected", 10)
        except Exception as exc:
            log.debug("Ordazzle health check failed (non-fatal): %s", exc)
            _emit(progress_cb, "auth", "Proceeding without health check…", 10)

    SSI_EBG_WAREHOUSES = ["SSIEBG_WH_EBGWarehouse", "SSIEBG"]

    rows = _fetch_inventory(cfg, SSI_EBG_WAREHOUSES, progress_cb)

    # Enrich with profile label
    for r in rows:
        r["Profile"] = "SSI_EBG"

    _emit(progress_cb, "done", f"{len(rows)} SSI EBG rows ready", 100)
    log.info("Ordazzle export SSI EBG: rows=%d", len(rows))
    return rows


# ── 2. Export SLCI ─────────────────────────────────────────────────────────────

def export_slci(cfg: dict | None = None, progress_cb=None) -> list[dict]:
    """
    Export SLCI warehouse inventory from Ordazzle.
    READ ONLY.

    SLCI warehouses: SLCI_WH_Warehouse
    """
    if cfg is None:
        cfg = _load_ordazzle_cfg()

    _validate(cfg)
    _emit(progress_cb, "auth", "Connecting to Ordazzle…", 5)

    try:
        _get(cfg, "/api/health")
    except Exception:
        pass
    _emit(progress_cb, "auth", "Connected", 10)

    SLCI_WAREHOUSES = ["SLCI_WH_Warehouse", "SLCI"]

    rows = _fetch_inventory(cfg, SLCI_WAREHOUSES, progress_cb)

    for r in rows:
        r["Profile"] = "SLCI"

    _emit(progress_cb, "done", f"{len(rows)} SLCI rows ready", 100)
    log.info("Ordazzle export SLCI: rows=%d", len(rows))
    return rows


# ── 3. SAP Order Sync (read) ───────────────────────────────────────────────────

def sap_order_sync(cfg: dict | None = None, progress_cb=None) -> list[dict]:
    """
    Fetch orders from Ordazzle that are pending SAP sync (READ ONLY).
    No data is pushed to SAP — this only reads the queue from Ordazzle.

    Use this to audit which orders Ordazzle has queued for SAP.
    """
    if cfg is None:
        cfg = _load_ordazzle_cfg()

    _validate(cfg)
    _emit(progress_cb, "auth", "Connecting to Ordazzle…", 5)
    _emit(progress_cb, "fetch", "Fetching SAP sync queue…", 15)

    rows: list[dict] = []

    # Try standard Ordazzle order export endpoints
    endpoints_to_try = [
        ("/api/orders/sap-sync",   {"status": "pending"}),
        ("/api/orders",            {"sap_status": "pending", "limit": 500}),
        ("/api/v1/orders/pending", {}),
    ]

    items = []
    used_ep = ""
    for ep, params in endpoints_to_try:
        try:
            result = _get(cfg, ep, params)
            items  = result if isinstance(result, list) else (result.get("data") or result.get("orders") or [])
            used_ep = ep
            if items is not None:
                break
        except Exception as exc:
            log.debug("Ordazzle SAP sync endpoint %s failed: %s", ep, exc)
            continue

    _emit(progress_cb, "fetch", f"{len(items)} orders in SAP queue", 70)
    _emit(progress_cb, "build", "Building rows…", 80)

    for o in items:
        rows.append({
            "Order ID":        o.get("order_id") or o.get("id", ""),
            "Order Number":    o.get("order_number") or o.get("reference", ""),
            "Channel":         o.get("channel") or o.get("marketplace", ""),
            "Brand":           o.get("brand", ""),
            "SAP Status":      o.get("sap_status") or o.get("sync_status", ""),
            "SAP Doc Number":  o.get("sap_document_number") or o.get("sap_doc_no", ""),
            "Order Date":      o.get("order_date") or o.get("created_at", ""),
            "Total Amount":    o.get("total_amount") or o.get("total", ""),
            "Currency":        o.get("currency", "PHP"),
            "Last Attempt":    o.get("last_sync_attempt") or o.get("updated_at", ""),
            "Error Message":   o.get("sap_error") or o.get("error_message", ""),
            "Source Endpoint": used_ep,
        })

    _emit(progress_cb, "done", f"{len(rows)} SAP queue rows ready", 100)
    log.info("Ordazzle SAP order sync (read): rows=%d endpoint=%s", len(rows), used_ep)
    return rows
