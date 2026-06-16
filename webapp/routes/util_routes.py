"""
routes/util_routes.py — utility and read-only endpoints.

  GET  /              serve the SPA (app.html)
  GET  /api/health
  GET  /api/brands    list all brand names from settings
  GET  /api/runs      last 50 run-history entries
  GET  /api/audit     audit log (long-term: who changed what and when)
"""

import csv
import json
import logging
import os
import sqlite3
from datetime import date, datetime

from flask import Blueprint, jsonify, make_response, request, send_from_directory

from helpers import (
    AUDIT_LOG_FILE,
    PULL_HISTORY_FILE,
    _HERE,
    _ROOT,
    load_settings,
)
from routes.auth_routes import login_required

log = logging.getLogger(__name__)
util_bp = Blueprint("util", __name__)


@login_required
@util_bp.route("/")
def index():
    """Serve the single-page app, with caching disabled so updates show immediately."""
    templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
    response = make_response(send_from_directory(templates_dir, "app.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@login_required
@util_bp.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@login_required
@util_bp.route("/api/brands")
def api_brands():
    """Return unique brand names from all warehouses in settings."""
    settings = load_settings()
    brands = sorted({
        brand
        for warehouse in settings.get("warehouses", [])
        for brand in warehouse.get("brands", [])
        if brand
    })
    return jsonify({"brands": brands})


@login_required
@util_bp.route("/api/runs")
def api_runs():
    """Return last 50 run-history entries by reading run_history.csv directly."""
    history_file = os.path.join(_ROOT, "run_history.csv")
    if not os.path.exists(history_file):
        return jsonify({"runs": []})
    try:
        with open(history_file, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return jsonify({"runs": rows[-50:][::-1]})  # newest first
    except Exception as e:
        log.warning("Could not load run_history.csv: %s", e)
        return jsonify({"runs": []})


# ══════════════════════════════════════════════════════════════════════════
#  Audit log   (long-term)
# ══════════════════════════════════════════════════════════════════════════

@login_required
@util_bp.route("/api/audit")
def api_audit():
    """
    Return audit log entries, newest first.
    Accepts optional query params:
      ?limit=N     (default 100, max 1000)
      ?action=xxx  filter by action name substring
    """
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
    except (TypeError, ValueError):
        limit = 100
    action_filter = request.args.get("action", "").lower()

    if not os.path.exists(AUDIT_LOG_FILE):
        return jsonify({"entries": [], "total": 0})

    try:
        with open(AUDIT_LOG_FILE, encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        log.warning("Could not read audit_log.json: %s", e)
        return jsonify({"entries": [], "total": 0, "error": str(e)})

    if action_filter:
        entries = [e for e in entries if action_filter in e.get("action", "").lower()]

    total = len(entries)
    entries = list(reversed(entries[-limit:]))
    return jsonify({"entries": entries, "total": total})


# ══════════════════════════════════════════════════════════════════════════
#  Metrics   (dashboard + sync monitor)
# ══════════════════════════════════════════════════════════════════════════

@login_required
@util_bp.route("/api/metrics")
def api_metrics():
    """
    Return real stats derived from pull_history.json, audit_log.json,
    settings.json (warehouses/brands), and oms.db.
    """
    # ── pull history ────────────────────────────────────────────────────
    pulls = []
    if os.path.exists(PULL_HISTORY_FILE):
        try:
            with open(PULL_HISTORY_FILE, encoding="utf-8") as f:
                pulls = json.load(f)
        except Exception:
            pulls = []

    total_pulls = len(pulls)
    total_skus = sum(pull.get("rows", 0) for pull in pulls)
    today_str = date.today().isoformat()
    today_pulls = [pull for pull in pulls if pull.get("pulled_at", "").startswith(today_str)]
    today_skus = sum(pull.get("rows", 0) for pull in today_pulls)

    brand_skus: dict = {}
    for pull in pulls:
        brand = pull.get("brand", "Unknown")
        brand_skus[brand] = brand_skus.get(brand, 0) + pull.get("rows", 0)

    chart_pulls = pulls[-15:]
    throughput_data = [pull.get("rows", 0) for pull in chart_pulls]
    throughput_labels = [pull.get("pulled_at", "")[-5:] for pull in chart_pulls]

    # ── audit log ───────────────────────────────────────────────────────
    audit_entries = []
    if os.path.exists(AUDIT_LOG_FILE):
        try:
            with open(AUDIT_LOG_FILE, encoding="utf-8") as f:
                audit_entries = json.load(f)
        except Exception:
            audit_entries = []

    activity = []
    for entry in audit_entries:
        activity.append({
            "ts": entry.get("ts", ""),
            "action": entry.get("action", "").upper(),
            "detail": str(entry.get("detail", "")),
            "level": "info",
            "source": "audit",
        })
    for pull in pulls:
        activity.append({
            "ts": pull.get("pulled_at", ""),
            "action": "ZALORA_PULL",
            "detail": f"{pull.get('brand', '')} — {pull.get('rows', 0):,} SKUs",
            "level": "info",
            "source": "pull",
        })
    activity.sort(key=lambda item: item["ts"], reverse=True)

    # ── oms.db counts ───────────────────────────────────────────────────
    db_path = os.path.join(_HERE, "oms.db")
    job_count = disc_count = retry_count = 0
    active_jobs = failed_jobs = 0
    open_discs = high_discs = 0
    disc_by_channel: dict = {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs")
        job_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM jobs WHERE active=1")
        active_jobs = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM jobs WHERE last_status='failed'")
        failed_jobs = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM discrepancies")
        disc_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM discrepancies WHERE status IN ('open','escalated')")
        open_discs = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM discrepancies WHERE severity='high'")
        high_discs = cur.fetchone()[0]
        cur.execute("SELECT channel, COUNT(*) FROM discrepancies GROUP BY channel")
        disc_by_channel = dict(cur.fetchall())
        cur.execute("SELECT COUNT(*) FROM retry_queue")
        retry_count = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass

    success_jobs = active_jobs - failed_jobs
    success_rate = round((success_jobs / active_jobs * 100), 1) if active_jobs else None

    return jsonify({
        "total_pulls": total_pulls,
        "total_skus": total_skus,
        "today_pulls": len(today_pulls),
        "today_skus": today_skus,
        "brand_skus": brand_skus,
        "throughput_data": throughput_data,
        "throughput_labels": throughput_labels,
        "recent_activity": activity[:20],
        "job_count": job_count,
        "active_jobs": active_jobs,
        "failed_jobs": failed_jobs,
        "disc_count": disc_count,
        "open_discs": open_discs,
        "high_discs": high_discs,
        "disc_by_channel": disc_by_channel,
        "retry_count": retry_count,
        "success_rate": success_rate,
    })


@login_required
@util_bp.route("/api/sync-monitor")
def api_sync_monitor():
    """
    Sync Monitor payload:
    - per-channel active/failed jobs
    - last pull time + sku totals
    - retry queue pressure
    - discrepancy counters
    """
    settings = load_settings()
    marketplaces = settings.get("marketplaces", [])
    type_to_channel = {
        "zalora": "Zalora",
        "shopee": "Shopee",
        "lazada": "Lazada",
        "shopify": "Shopify",
        "tiktok": "TikTok Shop",
    }

    channels = sorted({
        type_to_channel.get((mp.get("type") or "").lower(), "")
        for mp in marketplaces if mp.get("type")
    })
    channels = [channel for channel in channels if channel]
    if not channels:
        channels = ["Zalora", "Shopee", "Lazada"]

    pulls = []
    if os.path.exists(PULL_HISTORY_FILE):
        try:
            with open(PULL_HISTORY_FILE, encoding="utf-8") as f:
                pulls = json.load(f)
        except Exception:
            pulls = []

    pull_by_channel = {channel: {"skus": 0, "last_pull_at": ""} for channel in channels}
    for pull in pulls:
        channel = (pull.get("channel") or "").strip()
        if not channel:
            filename = (pull.get("filename") or "").lower()
            if "zalora" in filename:
                channel = "Zalora"
            elif "shopee" in filename:
                channel = "Shopee"
            elif "lazada" in filename:
                channel = "Lazada"
        if channel not in pull_by_channel:
            continue
        pull_by_channel[channel]["skus"] += int(pull.get("rows", 0) or 0)
        pulled_at = pull.get("pulled_at", "")
        if pulled_at > (pull_by_channel[channel]["last_pull_at"] or ""):
            pull_by_channel[channel]["last_pull_at"] = pulled_at

    db_path = os.path.join(_HERE, "oms.db")
    channel_stats = {
        channel: {"active_jobs": 0, "failed_jobs": 0, "retry_items": 0, "open_discrepancies": 0}
        for channel in channels
    }
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            for channel in channels:
                cur.execute("SELECT COUNT(*) AS c FROM jobs WHERE channel=? AND active=1", (channel,))
                channel_stats[channel]["active_jobs"] = cur.fetchone()["c"]
                cur.execute("SELECT COUNT(*) AS c FROM jobs WHERE channel=? AND last_status='failed'", (channel,))
                channel_stats[channel]["failed_jobs"] = cur.fetchone()["c"]
                cur.execute("SELECT COUNT(*) AS c FROM retry_queue WHERE lower(channel)=lower(?)", (channel,))
                channel_stats[channel]["retry_items"] = cur.fetchone()["c"]
                cur.execute(
                    "SELECT COUNT(*) AS c FROM discrepancies WHERE lower(channel)=lower(?) AND status IN ('open','escalated')",
                    (channel,),
                )
                channel_stats[channel]["open_discrepancies"] = cur.fetchone()["c"]
            conn.close()
        except Exception:
            pass

    channel_cards = []
    for channel in channels:
        failed = channel_stats[channel]["failed_jobs"]
        retry = channel_stats[channel]["retry_items"]
        status = "ok"
        if failed > 0 or retry > 0:
            status = "warn"
        if retry >= 5:
            status = "err"
        channel_cards.append({
            "channel": channel,
            "status": status,
            "active_jobs": channel_stats[channel]["active_jobs"],
            "failed_jobs": failed,
            "retry_items": retry,
            "open_discrepancies": channel_stats[channel]["open_discrepancies"],
            "skus_pulled": pull_by_channel[channel]["skus"],
            "last_pull_at": pull_by_channel[channel]["last_pull_at"],
        })

    return jsonify({
        "channels": channel_cards,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })