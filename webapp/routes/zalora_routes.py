"""
routes/zalora_routes.py — Zalora pull endpoints.

  POST /api/zalora/pull                 start a pull job, return job_id
  GET  /api/zalora/pull/<job_id>/stream SSE progress stream
  GET  /api/zalora/download/<job_id>/<token>
  GET  /api/zalora/history

The actual data-fetching is in zalora_pull.do_pull().
This module only handles HTTP/SSE concerns (job management, streaming,
download token) so it can stay thin.
"""

import csv
import json
import logging
import os
import queue
import threading
import uuid
from datetime import datetime
from routes.auth_routes import login_required

from flask import Blueprint, Response, jsonify, request, send_file

from helpers import (
    load_settings,
    append_pull_history,
    write_audit,
    job_dir, save_state, load_state,
    is_download_token_valid, load_download_info,
    PULL_HISTORY_FILE,
    _HERE,
)
from routes.pull_helpers import (
    error_sse,
    rows_to_csv_bytes,
    save_pull_download,
    sse_frame,
)
from zalora_pull import do_pull
from inventory_pkg.utils import safe_filename

log = logging.getLogger(__name__)
zalora_bp = Blueprint("zalora", __name__)
_RUN_STATE_LOCK = threading.Lock()
_RUN_STATE: dict[str, dict] = {}
_SNAPSHOTS_DIR = os.path.join(_HERE, "snapshots", "zalora")


# ══════════════════════════════════════════════════════════════════════════════
#  Start a pull job
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@zalora_bp.route("/api/zalora/pull", methods=["POST"])
def api_zalora_pull():
    """Create a job_id and return it.  The client then opens the SSE stream."""
    data  = request.get_json(force=True)
    mp_id = (data.get("mp_id") or "").strip()
    if not mp_id:
        return jsonify({"error": "mp_id is required"}), 400

    s  = load_settings()
    mp = next((m for m in s.get("marketplaces", []) if m["id"] == mp_id), None)
    if not mp:
        return jsonify({"error": "Marketplace not found"}), 404
    if mp.get("type") != "zalora":
        return jsonify({"error": "Only Zalora marketplaces support a pull"}), 400

    job_id = str(uuid.uuid4())
    os.makedirs(job_dir(job_id), exist_ok=True)
    save_state(job_id, {"mp_id": mp_id, "status": "pending"})
    return jsonify({"job_id": job_id})


# ══════════════════════════════════════════════════════════════════════════════
#  SSE progress stream
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@zalora_bp.route("/api/zalora/pull/<job_id>/stream")
def api_zalora_stream(job_id: str):
    """
    Server-Sent Events stream for a Zalora pull job.

    do_pull() runs in a worker thread and pushes progress events into a
    queue.Queue.  This generator reads from that queue and yields SSE
    frames so the browser can show a live progress bar.
    """
    try:
        state = load_state(job_id)
    except Exception:
        return error_sse("Job not found or expired.")

    mp_id = state.get("mp_id", "")
    s     = load_settings()
    mp    = next((m for m in s.get("marketplaces", []) if m["id"] == mp_id), None)
    if not mp:
        return error_sse("Marketplace not found in settings.")

    brand = (mp.get("brand") or "").strip()
    q: queue.Queue = queue.Queue()

    def on_progress(step: str, msg: str, pct: int) -> None:
        q.put(("progress", {"step": step, "msg": msg, "pct": pct}))

    def worker() -> None:
        with _RUN_STATE_LOCK:
            _RUN_STATE[job_id] = {
                "status": "running",
                "mp_id": mp_id,
                "brand": brand,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": "",
                "rows": 0,
                "error": "",
            }
        try:
            rows = do_pull(mp, progress_cb=on_progress)

            csv_bytes = rows_to_csv_bytes(rows)

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            filename = f"Zalora_Inventory_{safe_filename(brand)}_{timestamp}.csv"
            snap_dir = os.path.join(_SNAPSHOTS_DIR, mp_id)
            os.makedirs(snap_dir, exist_ok=True)
            snap_path = os.path.join(snap_dir, "latest.csv")
            with open(snap_path, "wb") as fh:
                fh.write(csv_bytes)

            dl_path, dl_token, _ = save_pull_download(job_id, csv_bytes, filename)

            download_url = f"/api/zalora/download/{job_id}/{dl_token}"
            append_pull_history({
                "pulled_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
                "brand":        brand,
                "mp_id":        mp_id,
                "channel":      "zalora",
                "rows":         len(rows),
                "filename":     filename,
                # permanent path so Unified Import always finds it
                "path":         snap_path,
                "download_url": download_url,
                "scheduled":    False,
            })
            write_audit("zalora_pull_completed", {
                "mp_id": mp_id,
                "brand": brand,
                "rows": len(rows),
                "filename": filename,
            })
            with _RUN_STATE_LOCK:
                _RUN_STATE[job_id].update({
                    "status": "success",
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": len(rows),
                    "error": "",
                })

            q.put(("done", {
                "rows":         len(rows),
                "filename":     filename,
                "download_url": download_url,
            }))
        except Exception as exc:
            log.exception("Zalora SSE pull failed for mp_id=%s: %s", mp_id, exc)
            with _RUN_STATE_LOCK:
                _RUN_STATE[job_id].update({
                    "status": "failed",
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": 0,
                    "error": str(exc),
                })
            q.put(("error", {"msg": str(exc)}))
        finally:
            q.put(None)   # sentinel — tells the generator to stop

    t = threading.Thread(target=worker, daemon=True, name=f"zalora-sse-{job_id[:8]}")
    t.start()

    def generate():
        yield sse_frame("progress", {"step": "start", "msg": f"Starting pull for {brand}…", "pct": 0})
        while True:
            item = q.get()
            if item is None:
                break
            event, payload = item
            yield sse_frame(event, payload)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",   # tell nginx not to buffer SSE
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Download
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@zalora_bp.route("/api/zalora/download/<job_id>/<token>")
def api_zalora_download(job_id: str, token: str):
    token_ok = is_download_token_valid(job_id, token)
    if token_ok is None:
        return jsonify({"error": "Download link expired"}), 404
    if not token_ok:
        return jsonify({"error": "Invalid token"}), 403

    dl_info = load_download_info(job_id)

    return send_file(
        dl_info["path"],
        as_attachment=True,
        download_name=dl_info["filename"],
        mimetype="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Pull history
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@zalora_bp.route("/api/zalora/inventory")
def api_zalora_inventory():
    """
    Read the last saved pull CSV — no live Zalora API call.
    Returns active/inactive rows only: seller_sku, quantity, status, mp_sku_id, mp_item_id.
    Query params: mp_id (required)
    """
    import csv as _csv

    mp_id = (request.args.get("mp_id") or "").strip()
    if not mp_id:
        return jsonify({"error": "mp_id is required"}), 400

    if not os.path.exists(PULL_HISTORY_FILE):
        return jsonify({"error": "No pull has been run yet. Fetch inventory first."}), 404

    try:
        with open(PULL_HISTORY_FILE) as f:
            history = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Could not read pull history: {e}"}), 500

    entry = next(
        (h for h in reversed(history) if h.get("mp_id") == mp_id and h.get("path")),
        None,
    )
    if not entry:
        return jsonify({"error": "No pull data found. Fetch inventory first."}), 404

    csv_path = entry.get("path", "")
    if not os.path.exists(csv_path):
        return jsonify({"error": "Pull file missing on disk. Re-fetch."}), 404

    ALLOWED = {"active", "inactive"}
    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                status = (row.get("Status") or "").strip().lower()
                if status not in ALLOWED:
                    continue
                rows.append({
                    "seller_sku": (row.get("Seller SKU") or "").strip(),
                    "quantity":   int(row.get("Quantity") or 0),
                    "status":     (row.get("Status") or "").strip(),
                    "mp_sku_id":  (row.get("MP SKU ID") or "").strip(),
                    "mp_item_id": (row.get("MP ITEM ID") or "").strip(),
                })
    except Exception as e:
        return jsonify({"error": f"Failed to read CSV: {e}"}), 500

    return jsonify({"rows": rows, "total": len(rows), "pulled_at": entry.get("pulled_at", "")})


@login_required
@zalora_bp.route("/api/zalora/history")
def api_zalora_history():
    if not os.path.exists(PULL_HISTORY_FILE):
        return jsonify({"history": []})
    try:
        with open(PULL_HISTORY_FILE) as f:
            history = json.load(f)
        # Strip raw filesystem paths before sending to the client
        for entry in history:
            entry.pop("path", None)
        return jsonify({"history": list(reversed(history[-100:]))})
    except Exception as e:
        log.warning("Could not read pull_history.json: %s", e)
        return jsonify({"history": []})


@login_required
@zalora_bp.route("/api/zalora/runs/status")
def api_zalora_run_status():
    """
    Live run state for UI persistence across page/module changes.
    """
    with _RUN_STATE_LOCK:
        runs = [dict({"job_id": jid}, **st) for jid, st in _RUN_STATE.items()]
    runs.sort(key=lambda r: (r.get("started_at") or "", r.get("job_id")), reverse=True)
    running_by_mp = {}
    latest_by_mp = {}
    for run in runs:
        mp_id = run.get("mp_id") or ""
        if not mp_id:
            continue
        if run.get("status") == "running":
            running_by_mp[mp_id] = True
        if mp_id not in latest_by_mp:
            latest_by_mp[mp_id] = run
    return jsonify({
        "running_by_mp": running_by_mp,
        "latest_by_mp": latest_by_mp,
        "runs": runs[:100],
    })