"""
Shared SSE pull-route helpers for marketplace inventory pulls.

Shopee and Lazada routes share the same HTTP/SSE/job lifecycle; Zalora adds
snapshot persistence on top but reuses the primitives here.
"""

import csv
import io
import json
import logging
import os
import queue
import threading
import uuid
from collections.abc import Callable
from datetime import datetime

from flask import Blueprint, Response, jsonify, request, send_file

from helpers import (
    PULL_HISTORY_FILE,
    append_pull_history,
    is_download_token_valid,
    job_dir,
    load_download_info,
    load_settings,
    load_state,
    save_state,
)
from inventory_pkg.utils import safe_filename

log = logging.getLogger(__name__)


def sse_frame(event: str, data: dict) -> str:
    """Format a single Server-Sent-Events frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def error_sse(message: str) -> Response:
    """Build a one-shot SSE response carrying a single error event."""

    def _emit():
        yield sse_frame("error", {"msg": message})

    return Response(_emit(), mimetype="text/event-stream")


def rows_to_csv_bytes(rows: list[dict]) -> bytes:
    """Convert a list of row dicts into UTF-8 (BOM) CSV bytes."""
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def save_pull_download(job_id: str, csv_bytes: bytes, filename: str) -> tuple[str, str, str]:
    """Write the CSV and its download token to disk for a completed job.

    Returns (download_path, download_token, filename).
    """
    download_token = str(uuid.uuid4())
    download_dir = os.path.join(job_dir(job_id), "results")
    os.makedirs(download_dir, exist_ok=True)
    download_path = os.path.join(download_dir, filename)

    with open(download_path, "wb") as fh:
        fh.write(csv_bytes)
    with open(os.path.join(download_dir, "download.json"), "w") as fh:
        json.dump({"type": "csv", "filename": filename, "path": download_path}, fh)
    with open(os.path.join(job_dir(job_id), "dl_token.txt"), "w") as fh:
        fh.write(download_token)

    return download_path, download_token, filename


def lookup_marketplace(mp_id: str, mp_type: str) -> dict | None:
    """Find a configured marketplace by id, scoped to the expected type."""
    settings = load_settings()
    marketplace = next(
        (m for m in settings.get("marketplaces", []) if m["id"] == mp_id), None
    )
    if not marketplace or marketplace.get("type") != mp_type:
        return None
    return marketplace


def register_pull_routes(
    bp: Blueprint,
    *,
    channel: str,
    mp_type: str,
    channel_label: str,
    filename_prefix: str,
    fetch_rows: Callable,
    login_required,
) -> None:
    """Register POST pull, SSE stream, download, and history routes on a blueprint."""

    @login_required
    @bp.route(f"/api/{channel}/pull", methods=["POST"])
    def start_pull():
        data = request.get_json(force=True)
        mp_id = (data.get("mp_id") or "").strip()
        if not mp_id:
            return jsonify({"error": "mp_id is required"}), 400

        marketplace = lookup_marketplace(mp_id, mp_type)
        if not marketplace:
            return jsonify({"error": "Marketplace not found"}), 404

        job_id = str(uuid.uuid4())
        os.makedirs(job_dir(job_id), exist_ok=True)
        save_state(job_id, {"mp_id": mp_id, "status": "pending"})
        return jsonify({"job_id": job_id})

    @login_required
    @bp.route(f"/api/{channel}/pull/<job_id>/stream")
    def stream_pull(job_id: str):
        try:
            state = load_state(job_id)
        except Exception:
            return error_sse("Job not found or expired.")

        mp_id = state.get("mp_id", "")
        marketplace = lookup_marketplace(mp_id, mp_type)
        if not marketplace:
            return error_sse("Marketplace not found in settings.")

        brand = (marketplace.get("brand") or "").strip()
        event_queue: queue.Queue = queue.Queue()

        def on_progress(step: str, msg: str, pct: int) -> None:
            event_queue.put(("progress", {"step": step, "msg": msg, "pct": pct}))

        def worker() -> None:
            try:
                rows = fetch_rows(marketplace, progress_cb=on_progress)
                csv_bytes = rows_to_csv_bytes(rows)
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
                filename = f"{filename_prefix}_{safe_filename(brand)}_{timestamp}.csv"
                download_path, download_token, _ = save_pull_download(
                    job_id, csv_bytes, filename
                )
                download_url = f"/api/{channel}/download/{job_id}/{download_token}"

                append_pull_history({
                    "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "brand": brand,
                    "mp_id": mp_id,
                    "channel": channel,
                    "rows": len(rows),
                    "filename": filename,
                    "path": download_path,
                    "download_url": download_url,
                    "scheduled": False,
                })

                event_queue.put(("done", {
                    "rows": len(rows),
                    "filename": filename,
                    "download_url": download_url,
                }))
            except Exception as exc:
                log.exception("%s pull failed for mp_id=%s: %s", channel_label, mp_id, exc)
                event_queue.put(("error", {"msg": str(exc)}))
            finally:
                # Sentinel value tells the generator below to stop streaming.
                event_queue.put(None)

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"{channel}-sse-{job_id[:8]}",
        ).start()

        def generate():
            yield sse_frame(
                "progress",
                {"step": "start", "msg": f"Starting {channel_label} pull for {brand}…", "pct": 0},
            )
            while True:
                item = event_queue.get()
                if item is None:
                    break
                event, payload = item
                yield sse_frame(event, payload)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @login_required
    @bp.route(f"/api/{channel}/download/<job_id>/<token>")
    def download_pull(job_id: str, token: str):
        token_is_valid = is_download_token_valid(job_id, token)
        if token_is_valid is None:
            return jsonify({"error": "Download link expired"}), 404
        if not token_is_valid:
            return jsonify({"error": "Invalid token"}), 403

        download_info = load_download_info(job_id)
        return send_file(
            download_info["path"],
            as_attachment=True,
            download_name=download_info["filename"],
            mimetype="text/csv",
        )

    @login_required
    @bp.route(f"/api/{channel}/history")
    def pull_history():
        if not os.path.exists(PULL_HISTORY_FILE):
            return jsonify({"history": []})
        try:
            with open(PULL_HISTORY_FILE) as f:
                history = json.load(f)
            channel_history = [h for h in history if h.get("channel") == channel]
            for entry in channel_history:
                entry.pop("path", None)
            return jsonify({"history": list(reversed(channel_history[-100:]))})
        except Exception as e:
            log.warning("Could not read pull_history.json: %s", e)
            return jsonify({"history": []})