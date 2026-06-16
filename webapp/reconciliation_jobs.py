"""
reconciliation_jobs.py

Three background jobs called by scheduler.py:

  unified_inventory_import_job()
      Reads latest marketplace pull CSVs → writes to unified_inventory_snapshot.
      Unchanged from before.

  discrepancy_engine_job()
      Compares unified_inventory_snapshot (marketplace stock) against
      ordazzle_snapshot (last manual Ordazzle upload from Inventory Check).
      No external API calls — both sides come from the local SQLite DB.

      Prerequisites:
        • At least one marketplace pull has been completed (Zalora/Shopee/Lazada).
        • At least one Ordazzle file has been uploaded through the Inventory
          Check module — that upload saves rows to ordazzle_snapshot automatically.

  cleanup_job()
      Prunes stale DB rows. Unchanged.
"""

import logging
import uuid
from datetime import datetime, timedelta

from database import get_db
from helpers import load_settings, resolve_warehouse, write_audit
from routes.unified_inventory_routes import _build_unified_records

log = logging.getLogger(__name__)


# ── helpers ────────────────────────────────────────────────────────────────────

def _safe_int(value, default=0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ── Jobs ───────────────────────────────────────────────────────────────────────

def unified_inventory_import_job() -> dict:
    """
    Import latest unified snapshot into internal SQLite DB only.
    Reads from snapshot CSV files written by the marketplace pull routes.
    """
    rows, _, has_batch = _build_unified_records()
    if not has_batch:
        return {"ok": False, "message": "No marketplace batch files available yet.", "rows": 0}

    run_id = str(uuid.uuid4())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    unique_rows = {}
    for r in rows:
        key = (r.get("brand", ""), r.get("mp_id", ""), r.get("sku", ""))
        unique_rows[key] = r

    # Only replace rows for mp_ids re-imported this run; other brands persist.
    mp_ids_this_run = {r.get("mp_id", "") for r in unique_rows.values() if r.get("mp_id")}

    with get_db() as conn:
        for mp_id in mp_ids_this_run:
            conn.execute(
                "DELETE FROM unified_inventory_snapshot WHERE mp_id = ?",
                (mp_id,),
            )
        conn.executemany(
            """
            INSERT INTO unified_inventory_snapshot (
                run_id, mp_id, brand, marketplace, sku, article, stock, status,
                mp_id_1_label, mp_id_1_value, mp_id_2_label, mp_id_2_value, pulled_at, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    run_id,
                    r.get("mp_id", ""),
                    r.get("brand", ""),
                    r.get("marketplace", ""),
                    r.get("sku", ""),
                    r.get("article", ""),
                    _safe_int(r.get("stock"), 0),
                    r.get("status", ""),
                    r.get("mp_id_1_label"),
                    r.get("mp_id_1_value"),
                    r.get("mp_id_2_label"),
                    r.get("mp_id_2_value"),
                    r.get("last_updated", ""),
                    now,
                )
                for r in unique_rows.values()
            ],
        )
        conn.commit()

    write_audit("unified_inventory_import_completed", {"run_id": run_id, "rows": len(unique_rows)})
    return {"ok": True, "run_id": run_id, "rows": len(unique_rows)}


def discrepancy_engine_job() -> dict:
    """
    Compare latest unified snapshot (marketplace) against last manual
    Ordazzle upload stored in ordazzle_snapshot.

    Both sides are read from local SQLite — no external API calls.

    Returns early with a clear message if either side is missing so the
    frontend / audit log explains what needs to happen first.
    """
    settings = load_settings()

    with get_db() as conn:
        snap_rows = conn.execute(
            """
            SELECT mp_id, brand, marketplace, sku, stock
            FROM unified_inventory_snapshot
            """
        ).fetchall()

        ord_rows = conn.execute(
            "SELECT sku, node_name, inv_stock FROM ordazzle_snapshot"
        ).fetchall()

    if not snap_rows:
        log.info("Discrepancy engine: no unified snapshot yet — skipping")
        return {
            "ok": False,
            "message": "No marketplace snapshot. Complete a Zalora/Shopee/Lazada pull first.",
            "discrepancies": 0,
        }

    if not ord_rows:
        log.info("Discrepancy engine: no ordazzle snapshot yet — skipping")
        return {
            "ok": False,
            "message": (
                "No Ordazzle snapshot. Upload an Ordazzle file through "
                "Inventory Check — it saves automatically."
            ),
            "discrepancies": 0,
        }

    # Build lookup: {node_name: {sku: inv_stock}}
    ord_index: dict[str, dict[str, int]] = {}
    for row in ord_rows:
        node = row["node_name"]
        if node not in ord_index:
            ord_index[node] = {}
        ord_index[node][row["sku"]] = row["inv_stock"]

    marketplaces = {m.get("id"): m for m in settings.get("marketplaces", [])}
    warehouses   = settings.get("warehouses", [])

    results      = []
    skipped_wh   = 0   # SKUs whose mp_id has no warehouse mapping

    for row in snap_rows:
        mp_id = row["mp_id"]
        sku   = (row["sku"] or "").strip()
        if not sku:
            continue

        mp = marketplaces.get(mp_id, {})
        wh = resolve_warehouse(mp, warehouses)
        if not wh:
            skipped_wh += 1
            continue

        wh_code = wh.get("code", "")
        node_map = ord_index.get(wh_code)
        if node_map is None:
            # No Ordazzle data uploaded yet for this warehouse — skip silently
            continue

        ord_qty = node_map.get(sku)
        if ord_qty is None:
            # SKU not present in last Ordazzle upload for this warehouse
            continue

        ch_qty = _safe_int(row["stock"], 0)
        diff   = ch_qty - ord_qty
        if diff == 0:
            continue

        severity = "high" if abs(diff) >= 10 else ("medium" if abs(diff) >= 3 else "low")
        results.append((
            sku,
            row["brand"] or "",
            row["marketplace"] or "",
            mp.get("name", ""),
            ord_qty,
            ch_qty,
            0,            # sap_qty — not available here
            diff,
            severity,
            "open",
            "[auto] discrepancy_engine",
        ))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute("DELETE FROM discrepancies WHERE note='[auto] discrepancy_engine'")
        if results:
            conn.executemany(
                """
                INSERT INTO discrepancies (
                    sku, brand, channel, shop,
                    ordazzle_qty, channel_qty, sap_qty, diff,
                    severity, last_checked, status, note
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [(*r[:9], now, r[9], r[10]) for r in results],
            )
        conn.commit()
        # Passive checkpoint: flush WAL pages to the main DB file when no
        # readers are blocking. Keeps WAL from growing unbounded and prevents
        # read-slowdown caused by a huge WAL backlog.
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

    if skipped_wh:
        log.warning(
            "Discrepancy engine: %d rows skipped — mp_id not mapped to a warehouse. "
            "Check Settings → Marketplaces → brand assignment.",
            skipped_wh,
        )

    write_audit(
        "discrepancy_engine_completed",
        {"discrepancies": len(results), "skipped_no_warehouse": skipped_wh},
    )
    log.info("Discrepancy engine: %d discrepancies written", len(results))
    return {"ok": True, "discrepancies": len(results), "skipped_no_warehouse": skipped_wh}


def cleanup_job() -> dict:
    """
    Internal maintenance:
      - Remove old auto discrepancies (resolved + older than 30 days)
      - Remove old retry queue records (older than 14 days)
      - ordazzle_snapshot rows are never cleaned — they represent the
        last known upload state and should persist until replaced.
    """
    cutoff_disc  = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_retry = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    removed = {"discrepancies": 0, "retry": 0}

    with get_db() as conn:
        cur = conn.execute(
            """
            DELETE FROM discrepancies
            WHERE note='[auto] discrepancy_engine'
              AND status='resolved'
              AND last_checked IS NOT NULL
              AND last_checked < ?
            """,
            (cutoff_disc,),
        )
        removed["discrepancies"] = cur.rowcount

        cur = conn.execute(
            "DELETE FROM retry_queue WHERE created_at < ?",
            (cutoff_retry,),
        )
        removed["retry"] = cur.rowcount
        conn.commit()

    write_audit("cleanup_job_completed", removed)
    return {"ok": True, **removed}