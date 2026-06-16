"""
routes/db_routes.py — CRUD API endpoints for SQLite-backed data.

Endpoints:
  GET    /api/jobs                 → list all jobs
  POST   /api/jobs                 → create a job
  PUT    /api/jobs/<id>            → update a job
  DELETE /api/jobs/<id>            → delete a job

  GET    /api/discrepancies        → list all discrepancies
  POST   /api/discrepancies        → create a discrepancy
  PUT    /api/discrepancies/<id>   → update a discrepancy
  DELETE /api/discrepancies/<id>   → delete a discrepancy

  GET    /api/retry                → list retry queue
  POST   /api/retry                → add to retry queue
  PUT    /api/retry/<id>           → update retry item
  DELETE /api/retry/<id>           → remove from retry queue
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime
from routes.auth_routes import login_required

from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import get_db
from reconciliation_jobs import unified_inventory_import_job, discrepancy_engine_job, cleanup_job

db_bp = Blueprint("db_bp", __name__)
log = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def sqlite_row_to_dict(row):
    return dict(row) if row else None


def _first_present_value(data: dict, *keys, default=""):
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def _first_present_int(data: dict, *keys, default=0):
    return int(_first_present_value(data, *keys, default=default) or default)


# ══════════════════════════════════════════════════════════════════════════════
#  JOBS
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@db_bp.route("/api/jobs", methods=["GET"])
def get_jobs():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    jobs = []
    for r in rows:
        j = sqlite_row_to_dict(r)
        j["notify_users"]  = json.loads(j.get("notify_users") or "[]")
        j["active"]        = bool(j["active"])
        j["notify_on_fail"] = bool(j["notify_on_fail"])
        jobs.append(j)
    return jsonify(jobs)


@login_required
@db_bp.route("/api/jobs", methods=["POST"])
def create_job():
    data         = request.get_json(force=True)
    notify_users = json.dumps(_first_present_value(data, "notify_users", default=[]))
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO jobs
              (job_name, channel, shop, fn, freq, active,
               last_exec, last_status, start_date,
               notify_on_fail, notify_users, brand)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            _first_present_value(data, "job_name", "jobName"),
            data.get("channel", ""),
            data.get("shop", ""),
            data.get("fn", ""),
            data.get("freq", "Every 5 mins"),
            1 if data.get("active", True) else 0,
            _first_present_value(data, "last_exec", "lastExec", default=None),
            _first_present_value(data, "last_status", "lastStatus", default=None),
            _first_present_value(data, "start_date", "startDate", default=None),
            1 if _first_present_value(data, "notify_on_fail", "notifyOnFail", default=False) else 0,
            notify_users,
            data.get("brand", ""),
        ))
        conn.commit()
        new_id = cur.lastrowid
    return jsonify({"id": new_id, "ok": True}), 201


@login_required
@db_bp.route("/api/jobs/<int:job_id>", methods=["PUT"])
def update_job(job_id):
    data         = request.get_json(force=True)
    notify_users = json.dumps(_first_present_value(data, "notify_users", "notifyUsers", default=[]))
    with get_db() as conn:
        conn.execute("""
            UPDATE jobs SET
              job_name=?, channel=?, shop=?, fn=?, freq=?, active=?,
              last_exec=?, last_status=?, start_date=?,
              notify_on_fail=?, notify_users=?, brand=?
            WHERE id=?
        """, (
            _first_present_value(data, "job_name", "jobName"),
            data.get("channel", ""),
            data.get("shop", ""),
            data.get("fn", ""),
            data.get("freq", "Every 5 mins"),
            1 if data.get("active", True) else 0,
            _first_present_value(data, "last_exec", "lastExec", default=None),
            _first_present_value(data, "last_status", "lastStatus", default=None),
            _first_present_value(data, "start_date", "startDate", default=None),
            1 if _first_present_value(data, "notify_on_fail", "notifyOnFail", default=False) else 0,
            notify_users,
            data.get("brand", ""),
            job_id,
        ))
        conn.commit()
    return jsonify({"ok": True})


@login_required
@db_bp.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    with get_db() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
#  DISCREPANCIES
# ══════════════════════════════════════════════════════════════════════════════

@db_bp.route("/api/discrepancies", methods=["GET"])
@login_required
def get_discrepancies():
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM discrepancies ORDER BY id").fetchall()
        return jsonify([sqlite_row_to_dict(r) for r in rows])
    except Exception as exc:
        log.error("get_discrepancies failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@login_required
@db_bp.route("/api/discrepancies", methods=["POST"])
def create_discrepancy():
    data      = request.get_json(force=True)
    ordazzle  = _first_present_int(data, "ordazzle_qty", "ordazzleQty")
    channel   = _first_present_int(data, "channel_qty", "channelQty")
    sap       = _first_present_int(data, "sap_qty", "sapQty")
    diff      = channel - ordazzle
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO discrepancies
              (sku, brand, channel, shop,
               ordazzle_qty, channel_qty, sap_qty, diff,
               severity, last_checked, status, note)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),?,?)
        """, (
            data.get("sku", ""),
            data.get("brand", ""),
            data.get("channel", ""),
            data.get("shop", ""),
            ordazzle, channel, sap, diff,
            data.get("severity", "low"),
            data.get("status", "open"),
            data.get("note", ""),
        ))
        conn.commit()
        new_id = cur.lastrowid
    return jsonify({"id": new_id, "ok": True}), 201


@login_required
@db_bp.route("/api/discrepancies/<int:disc_id>", methods=["PUT"])
def update_discrepancy(disc_id):
    data = request.get_json(force=True)
    with get_db() as conn:
        conn.execute("""
            UPDATE discrepancies SET
              sku=?, brand=?, channel=?, shop=?,
              ordazzle_qty=?, channel_qty=?, sap_qty=?, diff=?,
              severity=?, status=?, note=?
            WHERE id=?
        """, (
            data.get("sku", ""),
            data.get("brand", ""),
            data.get("channel", ""),
            data.get("shop", ""),
            _first_present_int(data, "ordazzle_qty", "ordazzleQty"),
            _first_present_int(data, "channel_qty", "channelQty"),
            _first_present_int(data, "sap_qty", "sapQty"),
            int(data.get("diff") or 0),
            data.get("severity", "low"),
            data.get("status", "open"),
            data.get("note", ""),
            disc_id,
        ))
        conn.commit()
    return jsonify({"ok": True})


@login_required
@db_bp.route("/api/discrepancies/<int:disc_id>", methods=["DELETE"])
def delete_discrepancy(disc_id):
    with get_db() as conn:
        conn.execute("DELETE FROM discrepancies WHERE id=?", (disc_id,))
        conn.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
#  RETRY QUEUE
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@db_bp.route("/api/retry", methods=["GET"])
def get_retry():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM retry_queue ORDER BY created_at DESC"
        ).fetchall()
    return jsonify([sqlite_row_to_dict(r) for r in rows])


@login_required
@db_bp.route("/api/retry", methods=["POST"])
def create_retry():
    data = request.get_json(force=True)
    rid  = data.get("id") or f"RTQ-{uuid.uuid4().hex[:6].upper()}"
    now  = datetime.now().strftime("%H:%M:%S")
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO retry_queue
              (id, job_name, brand, channel,
               attempts, max_attempts, next_retry,
               error, last_attempt, priority)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            rid,
            _first_present_value(data, "job_name", "jobName"),
            data.get("brand", ""),
            data.get("channel", ""),
            int(data.get("attempts", 0)),
            _first_present_int(data, "max_attempts", "maxAttempts", default=3),
            _first_present_value(data, "next_retry", "nextRetry", default="—"),
            data.get("error", ""),
            _first_present_value(data, "last_attempt", "lastAttempt", default=now),
            data.get("priority", "medium"),
        ))
        conn.commit()
    return jsonify({"id": rid, "ok": True}), 201


@login_required
@db_bp.route("/api/retry/<string:item_id>", methods=["PUT"])
def update_retry(item_id):
    data = request.get_json(force=True)
    with get_db() as conn:
        conn.execute("""
            UPDATE retry_queue SET
              attempts=?, next_retry=?, error=?, priority=?, last_attempt=?
            WHERE id=?
        """, (
            int(data.get("attempts", 0)),
            _first_present_value(data, "next_retry", "nextRetry", default="—"),
            data.get("error", ""),
            data.get("priority", "medium"),
            _first_present_value(data, "last_attempt", "lastAttempt", default=""),
            item_id,
        ))
        conn.commit()
    return jsonify({"ok": True})


@login_required
@db_bp.route("/api/retry/<string:item_id>", methods=["DELETE"])
def delete_retry(item_id):
    with get_db() as conn:
        conn.execute("DELETE FROM retry_queue WHERE id=?", (item_id,))
        conn.commit()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
#  RETRY — TRIGGER NOW
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@db_bp.route("/api/retry/<string:item_id>/trigger", methods=["POST"])
def trigger_retry(item_id):
    """
    Immediately trigger a retry for a queue item.
    - Increments attempts counter
    - If attempts >= max_attempts → marks status = 'failed' (permanent)
    - Otherwise fires a Zalora pull if channel == Zalora, or marks re-queued
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from helpers import load_settings, write_audit
    from flask import current_app
    import uuid as _uuid
    from datetime import datetime as _dt

    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM retry_queue WHERE id=?", (item_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Item not found"}), 404

        item      = dict(row)
        attempts  = item["attempts"] + 1
        max_att   = item["max_attempts"] or 3
        channel   = (item["channel"] or "").lower()
        brand     = item["brand"] or ""
        job_name  = item["job_name"] or ""

        if attempts >= max_att:
            # Permanent fail — add status column value via priority field trick
            conn.execute("""
                UPDATE retry_queue
                SET attempts=?, last_attempt=?, priority='permanent',
                    next_retry='—', error=?
                WHERE id=?
            """, (attempts, now, item["error"] + f" [PERMANENT FAIL after {attempts} attempts]", item_id))
            conn.commit()
            write_audit("retry_permanent_fail", {"id": item_id, "brand": brand, "attempts": attempts})
            return jsonify({"ok": True, "status": "permanent_fail", "attempts": attempts})

        # Try to trigger Zalora pull if applicable
        result_status = "requeued"
        error_msg     = item["error"]

        if channel in ("zalora", "zalora pull"):
            settings = load_settings()
            mp = next(
                (m for m in settings.get("marketplaces", [])
                 if m.get("type") == "zalora" and (not brand or m.get("brand","").lower() == brand.lower())),
                None
            )
            if mp:
                try:
                    import requests as _req
                    pull_resp = _req.post(
                        "http://localhost:5000/api/zalora/pull",
                        json={"mp_id": mp["id"]},
                        timeout=5,
                    )
                    if pull_resp.ok:
                        result_status = "triggered"
                        error_msg     = ""
                    else:
                        error_msg = pull_resp.json().get("error", "Pull failed")
                except Exception as exc:
                    error_msg = str(exc)
            else:
                error_msg = "No matching Zalora marketplace found in settings"

        # Calculate next retry time (exponential backoff: 5min, 15min, 45min…)
        backoff_mins = 5 * (3 ** (attempts - 1))
        next_retry   = _dt.now().strftime(f"%H:%M +{backoff_mins}m")

        conn.execute("""
            UPDATE retry_queue
            SET attempts=?, last_attempt=?, next_retry=?, error=?
            WHERE id=?
        """, (attempts, now, next_retry, error_msg, item_id))
        conn.commit()

    write_audit("retry_triggered", {"id": item_id, "brand": brand, "attempts": attempts, "status": result_status})
    return jsonify({"ok": True, "status": result_status, "attempts": attempts})


@login_required
@db_bp.route("/api/retry/auto", methods=["POST"])
def auto_retry():
    """
    Auto-retry all non-permanent items whose next_retry time has passed.
    Called by scheduler or manually.
    """
    from helpers import write_audit
    from datetime import datetime as _dt

    triggered = []
    skipped   = []

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM retry_queue WHERE priority != 'permanent' ORDER BY created_at"
        ).fetchall()

    for row in rows:
        item = dict(row)
        if item["attempts"] < item["max_attempts"]:
            # Trigger via internal call
            from flask import current_app
            with current_app.test_request_context():
                trigger_retry(item["id"])
            triggered.append(item["id"])
        else:
            skipped.append(item["id"])

    write_audit("auto_retry_run", {"triggered": len(triggered), "skipped": len(skipped)})
    return jsonify({"ok": True, "triggered": len(triggered), "skipped": len(skipped)})


# ══════════════════════════════════════════════════════════════════════════════
#  RECONCILIATION JOBS (manual trigger)
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@db_bp.route("/api/jobs/unified-import/run", methods=["POST"])
def run_unified_import_now():
    result = unified_inventory_import_job()
    status = 200 if result.get("ok") else 422
    return jsonify(result), status


@login_required
@db_bp.route("/api/jobs/discrepancy-engine/run", methods=["POST"])
def run_discrepancy_engine_now():
    result = discrepancy_engine_job()
    status = 200 if result.get("ok") else 422
    return jsonify(result), status


@login_required
@db_bp.route("/api/jobs/cleanup/run", methods=["POST"])
def run_cleanup_now():
    result = cleanup_job()
    return jsonify(result), 200