"""
routes/unified_inventory_routes.py — Unified Inventory Record API.

Rules
-----
  - Latest marketplace pull per (mp_id, sku) is kept as the base record.
  - Pure READ-ONLY — no marketplace writes, no Ordazzle mutations.
  - Filtering and counting are done IN SQL — Python never loads the full table.
  - Pagination: default 500 rows/page, max 2000. Use ?page= & ?page_size=.

Endpoints
---------
  GET  /api/inventory/unified        → paginated, filtered rows
  GET  /api/inventory/unified/meta   → filter options + timestamps (no row load)
"""

import csv
import json
import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request, Response
from routes.auth_routes import login_required
from helpers import load_settings, PULL_HISTORY_FILE
from database import get_db

log = logging.getLogger(__name__)
unified_bp = Blueprint("unified_inventory", __name__)

PAGE_SIZE_DEFAULT = 500
PAGE_SIZE_MAX     = 2000

# ── helpers ────────────────────────────────────────────────────────────────────

def _normalize_channel_type(channel: str) -> str:
    return (channel or "").strip().lower()


def _load_pull_history() -> list[dict]:
    if not os.path.exists(PULL_HISTORY_FILE):
        return []
    try:
        with open(PULL_HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read pull_history.json: %s", exc)
        return []


def _latest_pulls_per_mp(history: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in history:
        mp_id = entry.get("mp_id") or ""
        if not mp_id:
            continue
        if mp_id not in latest or entry.get("pulled_at", "") > latest[mp_id].get("pulled_at", ""):
            latest[mp_id] = entry
    return latest


def _read_csv_rows(csv_path: str) -> list[dict]:
    if not csv_path or not os.path.exists(csv_path):
        return []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as exc:
        log.warning("Could not read CSV %s: %s", csv_path, exc)
        return []


def _channel_from_filename(filename: str) -> str:
    fname = (filename or "").lower()
    for channel in ("zalora", "shopee", "lazada"):
        if channel in fname:
            return channel
    return ""


def _resolve_channel(entry: dict, mp: dict | None = None) -> str:
    channel = _normalize_channel_type(entry.get("channel") or "")
    if not channel and mp:
        channel = _normalize_channel_type(mp.get("type") or "")
    if not channel:
        channel = _channel_from_filename(entry.get("filename") or "")
    return channel


def _normalize_shopee_status(status: str) -> str:
    if status == "normal":
        return "active"
    if status in ("banned", "deleted", "unlist"):
        return "inactive"
    return status or "unknown"


def _normalize_lazada_status(status: str) -> str:
    if status in ("active", ""):
        return "active"
    if status in ("inactive", "deleted", "banned"):
        return "inactive"
    return status or "unknown"


def _normalise_zalora(raw: dict, mp: dict, pulled_at: str) -> dict | None:
    status = (raw.get("Status") or "").strip().lower()
    if status not in ("active", "inactive"):
        return None
    sku = (raw.get("Seller SKU") or "").strip()
    if not sku:
        return None
    return {
        "sku":           sku,
        "article":       (raw.get("Product Name") or sku).strip(),
        "stock":         int(raw.get("Quantity") or 0),
        "status":        status,
        "brand":         (mp.get("brand") or raw.get("Brand") or "").strip(),
        "marketplace":   "Zalora",
        "mp_id":         mp.get("id", ""),
        "mp_label":      mp.get("name") or mp.get("label") or "Zalora",
        "mp_id_1_label": "MP SKU ID",
        "mp_id_1_value": (raw.get("MP SKU ID") or "").strip(),
        "mp_id_2_label": "MP Item ID",
        "mp_id_2_value": (raw.get("MP ITEM ID") or raw.get("MP Item ID") or "").strip(),
        "last_updated":  pulled_at,
    }


def _normalise_shopee(raw: dict, mp: dict, pulled_at: str) -> dict | None:
    status = (raw.get("Item Status") or "").strip().lower()
    norm_status = _normalize_shopee_status(status)
    sku = (raw.get("Model SKU") or raw.get("Item SKU") or "").strip()
    if not sku:
        return None
    return {
        "sku":           sku,
        "article":       (raw.get("Item Name") or sku).strip(),
        "stock":         int(raw.get("Current Stock") or 0),
        "status":        norm_status,
        "brand":         (mp.get("brand") or raw.get("Brand") or "").strip(),
        "marketplace":   "Shopee",
        "mp_id":         mp.get("id", ""),
        "mp_label":      mp.get("name") or mp.get("label") or "Shopee",
        "mp_id_1_label": "Item ID",
        "mp_id_1_value": str(raw.get("Item ID") or "").strip(),
        "mp_id_2_label": "Model ID",
        "mp_id_2_value": str(raw.get("Model ID") or "").strip(),
        "last_updated":  pulled_at,
    }


def _normalise_lazada(raw: dict, mp: dict, pulled_at: str) -> dict | None:
    status = (raw.get("Status") or "").strip().lower()
    norm_status = _normalize_lazada_status(status)
    sku = (raw.get("Seller SKU") or raw.get("SKU") or "").strip()
    if not sku:
        return None
    return {
        "sku":           sku,
        "article":       (raw.get("Product Name") or sku).strip(),
        "stock":         int(raw.get("Available") or raw.get("Quantity") or 0),
        "status":        norm_status,
        "brand":         (mp.get("brand") or raw.get("Brand") or "").strip(),
        "marketplace":   "Lazada",
        "mp_id":         mp.get("id", ""),
        "mp_label":      mp.get("name") or mp.get("label") or "Lazada",
        "mp_id_1_label": "Item ID",
        "mp_id_1_value": str(raw.get("Item ID") or "").strip(),
        "mp_id_2_label": "Shop SKU",
        "mp_id_2_value": (raw.get("Shop SKU") or "").strip(),
        "last_updated":  pulled_at,
    }


_NORMALISERS = {
    "zalora": _normalise_zalora,
    "shopee": _normalise_shopee,
    "lazada": _normalise_lazada,
}


def _connected_mp_ids() -> list[str]:
    """
    Return a list of mp_ids whose status is 'connected' in settings.json.
    Marketplaces that are 'disconnected' or have no status are excluded.
    This is used to gate all unified inventory queries so disconnected
    brands never appear in filters, dropdowns, or row results.
    """
    settings = load_settings()
    return [
        m["id"]
        for m in settings.get("marketplaces", [])
        if m.get("status", "connected") == "connected"
    ]


def _build_unified_records() -> tuple[list[dict], dict[str, str], bool]:
    """
    Build the merged unified inventory list from the latest pull per mp_id.
    Returns: (rows, mp_timestamps, has_any_batch)
    """
    history  = _load_pull_history()
    latest   = _latest_pulls_per_mp(history)
    settings = load_settings()
    mp_map   = {m["id"]: m for m in settings.get("marketplaces", [])}

    has_any_batch = False
    mp_timestamps: dict[str, str] = {}
    rows: list[dict] = []

    for mp_id, entry in latest.items():
        csv_path  = entry.get("path", "")
        pulled_at = entry.get("pulled_at", "")
        mp        = mp_map.get(mp_id, {"id": mp_id, "brand": entry.get("brand", ""), "type": ""})
        channel   = _resolve_channel(entry, mp)

        normaliser = _NORMALISERS.get(channel)
        if not normaliser:
            log.debug("No normaliser for channel '%s' (mp_id=%s)", channel, mp_id)
            continue

        if not csv_path or not os.path.exists(csv_path):
            log.debug("CSV not found on disk for mp_id=%s (path=%s)", mp_id, csv_path)
            continue

        has_any_batch = True
        mp_timestamps[mp_id] = pulled_at
        if not mp.get("type"):
            mp["type"] = channel

        for raw in _read_csv_rows(csv_path):
            rec = normaliser(raw, mp, pulled_at)
            if rec:
                rows.append(rec)

    return rows, mp_timestamps, has_any_batch


# ── SQL filter builder ─────────────────────────────────────────────────────────

def _build_where(
    sku_q: str,
    status_q: str,
    brand_q: str,
    mp_type_q: str,
    mp_id_q: str,
    date_q: str,
    stock_op: str,
    stock_val: str,
    connected_mp_ids: list[str] | None = None,
) -> tuple[str, list]:
    """Return (WHERE clause string, params list). Clause starts with 'WHERE' if non-empty."""
    parts: list[str] = []
    params: list    = []

    ALLOWED_OPS = {">", ">=", "<", "<=", "="}

    # Always filter to connected marketplaces only
    if connected_mp_ids is not None:
        if not connected_mp_ids:
            # No connected marketplaces at all — return nothing
            parts.append("1 = 0")
        else:
            placeholders = ",".join("?" * len(connected_mp_ids))
            parts.append(f"mp_id IN ({placeholders})")
            params += connected_mp_ids

    if sku_q:
        parts.append("(sku LIKE ? OR article LIKE ? OR mp_id_1_value LIKE ? OR mp_id_2_value LIKE ?)")
        like = f"%{sku_q}%"
        params += [like, like, like, like]

    if status_q and status_q != "all":
        parts.append("status = ?")
        params.append(status_q)

    if brand_q:
        parts.append("LOWER(brand) = LOWER(?)")
        params.append(brand_q)

    if mp_id_q:
        parts.append("mp_id = ?")
        params.append(mp_id_q)
    elif mp_type_q and mp_type_q != "all":
        parts.append("LOWER(marketplace) = LOWER(?)")
        params.append(mp_type_q)

    if date_q:
        parts.append("pulled_at LIKE ?")
        params.append(f"{date_q}%")

    if stock_val.strip() != "":
        try:
            sv = float(stock_val)
            op = stock_op if stock_op in ALLOWED_OPS else ">"
            parts.append(f"stock {op} ?")
            params.append(sv)
        except ValueError:
            pass

    where = ("WHERE " + " AND ".join(parts)) if parts else ""
    return where, params


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/inventory/unified/meta
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@unified_bp.route("/api/inventory/unified/meta", methods=["GET"])
def unified_meta():
    """
    Return filter options and timestamps using aggregate SQL — never loads rows.
    Only includes data from marketplaces with status='connected'.
    """
    settings         = load_settings()
    mp_map           = {m["id"]: m for m in settings.get("marketplaces", [])}
    connected_ids    = _connected_mp_ids()

    with get_db() as conn:
        has_batch = bool(conn.execute(
            "SELECT 1 FROM unified_inventory_snapshot LIMIT 1"
        ).fetchone())

        if not has_batch:
            return jsonify({
                "has_batch":    False,
                "marketplaces": [],
                "brands":       [],
                "pull_dates":   [],
            })

        if not connected_ids:
            return jsonify({
                "has_batch":    True,
                "marketplaces": [],
                "brands":       [],
                "pull_dates":   [],
            })

        placeholders = ",".join("?" * len(connected_ids))

        # Distinct brands — only from connected mp_ids
        brands = [r[0] for r in conn.execute(
            f"SELECT DISTINCT brand FROM unified_inventory_snapshot "
            f"WHERE brand != '' AND mp_id IN ({placeholders}) ORDER BY brand",
            connected_ids,
        ).fetchall()]

        # Distinct marketplaces — only connected ones
        marketplaces_raw = conn.execute(
            f"SELECT DISTINCT mp_id, marketplace, brand, MAX(pulled_at) as pulled_at "
            f"FROM unified_inventory_snapshot WHERE mp_id IN ({placeholders}) GROUP BY mp_id",
            connected_ids,
        ).fetchall()

        # Distinct pull dates — only from connected mp_ids
        pull_dates = [r[0] for r in conn.execute(
            f"SELECT DISTINCT SUBSTR(pulled_at, 1, 10) as d "
            f"FROM unified_inventory_snapshot WHERE pulled_at IS NOT NULL AND mp_id IN ({placeholders}) "
            f"ORDER BY d DESC",
            connected_ids,
        ).fetchall()]

    marketplaces = []
    for row in marketplaces_raw:
        mp_id = row["mp_id"]
        mp    = mp_map.get(mp_id, {})
        marketplaces.append({
            "mp_id":    mp_id,
            "label":    mp.get("name") or mp.get("label") or row["marketplace"],
            "type":     (row["marketplace"] or "").lower(),
            "brand":    row["brand"],
            "pulled_at": row["pulled_at"],
        })

    return jsonify({
        "has_batch":    True,
        "marketplaces": marketplaces,
        "brands":       brands,
        "pull_dates":   pull_dates,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/inventory/unified
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@unified_bp.route("/api/inventory/unified", methods=["GET"])
def get_unified_inventory():
    """
    Return paginated, SQL-filtered inventory rows. Never loads the full table.

    Query params:
      sku         — partial match on SKU / article / mp_id values
      status      — 'active' | 'inactive' | 'all'  (default 'all')
      brand       — exact match (case-insensitive)
      marketplace — 'zalora' | 'shopee' | 'lazada' | 'all'
      mp_id       — specific marketplace UUID (overrides marketplace)
      date        — YYYY-MM-DD prefix match on pulled_at
      stock_op    — '>' | '>=' | '<' | '<=' | '='  (default '>')
      stock_val   — numeric threshold
      sort        — column name  (default 'sku')
      dir         — 'asc' | 'desc'  (default 'asc')
      page        — 1-based page number  (default 1)
      page_size   — rows per page  (default 500, max 2000)
    """
    with get_db() as conn:
        has_batch = bool(conn.execute(
            "SELECT 1 FROM unified_inventory_snapshot LIMIT 1"
        ).fetchone())

    if not has_batch:
        return jsonify({
            "ok": False, "has_batch": False, "rows": [], "total": 0,
            "page": 1, "page_size": PAGE_SIZE_DEFAULT, "total_pages": 0,
            "mp_timestamps": {},
            "message": "No unified inventory snapshot available yet. Run Unified Import job first.",
        })

    # ── Parse query params ─────────────────────────────────────────────────────
    sku_q     = (request.args.get("sku")         or "").strip().lower()
    status_q  = (request.args.get("status")      or "all").strip().lower()
    brand_q   = (request.args.get("brand")       or "").strip()
    mp_type_q = (request.args.get("marketplace") or "all").strip().lower()
    mp_id_q   = (request.args.get("mp_id")       or "").strip()
    date_q    = (request.args.get("date")        or "").strip()
    stock_op  = (request.args.get("stock_op")    or ">").strip()
    stock_val = (request.args.get("stock_val")   or "").strip()

    # Sort — whitelist columns to prevent SQL injection
    SORT_COLS = {"sku", "article", "stock", "status", "brand", "marketplace", "pulled_at"}
    sort_col  = request.args.get("sort", "sku").strip().lower()
    sort_col  = sort_col if sort_col in SORT_COLS else "sku"
    sort_dir  = "DESC" if request.args.get("dir", "asc").strip().lower() == "desc" else "ASC"

    # Pagination
    try:
        page      = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(PAGE_SIZE_MAX, max(1, int(request.args.get("page_size", PAGE_SIZE_DEFAULT))))
    except ValueError:
        page_size = PAGE_SIZE_DEFAULT

    offset = (page - 1) * page_size

    # ── Build WHERE clause ─────────────────────────────────────────────────────
    where, params = _build_where(
        sku_q, status_q, brand_q, mp_type_q, mp_id_q, date_q, stock_op, stock_val,
        connected_mp_ids=_connected_mp_ids(),
    )

    with get_db() as conn:
        # Total matching rows — uses indexes, no data load
        total = conn.execute(
            f"SELECT COUNT(*) FROM unified_inventory_snapshot {where}", params
        ).fetchone()[0]

        # Paginated rows
        rows = conn.execute(
            f"""
            SELECT
                mp_id, brand, marketplace, sku, article, stock, status,
                mp_id_1_label, mp_id_1_value, mp_id_2_label, mp_id_2_value,
                pulled_at AS last_updated
            FROM unified_inventory_snapshot
            {where}
            ORDER BY {sort_col} {sort_dir}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        # mp_timestamps — lightweight aggregate
        mp_ts_rows = conn.execute(
            "SELECT mp_id, MAX(pulled_at) as pulled_at FROM unified_inventory_snapshot GROUP BY mp_id"
        ).fetchall()

    mp_timestamps = {r["mp_id"]: r["pulled_at"] for r in mp_ts_rows}
    total_pages   = max(1, (total + page_size - 1) // page_size)

    return jsonify({
        "ok":            True,
        "has_batch":     True,
        "rows":          [dict(r) for r in rows],
        "total":         total,
        "page":          page,
        "page_size":     page_size,
        "total_pages":   total_pages,
        "mp_timestamps": mp_timestamps,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/inventory/unified/export  (streaming CSV — no memory spike)
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@unified_bp.route("/api/inventory/unified/export", methods=["GET"])
def export_unified_csv():
    """
    Stream a CSV export of the full filtered result set.
    Uses a generator so memory usage stays flat even for 500k rows.
    """
    sku_q     = (request.args.get("sku")         or "").strip().lower()
    status_q  = (request.args.get("status")      or "all").strip().lower()
    brand_q   = (request.args.get("brand")       or "").strip()
    mp_type_q = (request.args.get("marketplace") or "all").strip().lower()
    mp_id_q   = (request.args.get("mp_id")       or "").strip()
    date_q    = (request.args.get("date")        or "").strip()
    stock_op  = (request.args.get("stock_op")    or ">").strip()
    stock_val = (request.args.get("stock_val")   or "").strip()

    where, params = _build_where(
        sku_q, status_q, brand_q, mp_type_q, mp_id_q, date_q, stock_op, stock_val,
        connected_mp_ids=_connected_mp_ids(),
    )

    COLS    = ["sku", "article", "stock", "status", "brand", "marketplace",
               "mp_id_1_value", "mp_id_2_value", "last_updated"]
    HEADERS = ["SKU", "Article / Product Name", "Stock", "Status", "Brand", "Marketplace",
               "MP SKU ID", "MP Item ID", "Last Pull"]

    def _csv_row(values: list) -> str:
        def _esc(v: str) -> str:
            v = str(v) if v is not None else ""
            return f'"{v.replace(chr(34), chr(34)*2)}"' if ("," in v or '"' in v or "\n" in v) else v
        return ",".join(_esc(v) for v in values) + "\r\n"

    def _generate():
        yield _csv_row(HEADERS)
        conn = get_db()
        try:
            cursor = conn.execute(
                f"""
                SELECT sku, article, stock, status, brand, marketplace,
                       mp_id_1_value, mp_id_2_value,
                       pulled_at AS last_updated
                FROM unified_inventory_snapshot
                {where}
                ORDER BY brand, marketplace, sku ASC
                """,
                params,
            )
            for row in cursor:
                yield _csv_row([row[c] for c in COLS])
        finally:
            conn.close()

    filename = f"unified_inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        _generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )   