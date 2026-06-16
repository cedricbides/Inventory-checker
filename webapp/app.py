"""
app.py — entry point.

Before the split this file was ~830 lines of mixed concerns.
Now it only does three things:
  1. Create and configure the Flask app.
  2. Register blueprints.
  3. Start the background scheduler and run the dev server.

All business logic lives in:
  helpers.py              shared I/O, settings, audit log
  zalora_pull.py          Zalora API fetch (no HTTP concerns)
  scheduler.py            APScheduler background tick
  routes/auth_routes      /api/auth/*  (login / logout / me)
  routes/settings_routes  /api/settings/*
  routes/check_routes     /api/check/*
  routes/zalora_routes    /api/zalora/*
  routes/shopee_routes    /api/shopee/*
  routes/lazada_routes    /api/lazada/*
  routes/util_routes      /, /api/health, /api/runs, /api/brands, /api/audit
"""

import logging
import os
from datetime import timedelta

from flask import Flask, jsonify, session
from flask_cors import CORS

# helpers must be imported first — it patches sys.path so inventory_pkg
# is importable from every module that follows.
from helpers import _HERE, cleanup_old_jobs

from routes.auth_routes     import auth_bp
from routes.settings_routes import settings_bp
from routes.check_routes    import check_bp
from routes.zalora_routes   import zalora_bp
from routes.util_routes     import util_bp
from routes.db_routes       import db_bp
from routes.shopee_routes   import shopee_bp
from routes.lazada_routes   import lazada_bp
from routes.unified_inventory_routes import unified_bp
from scheduler import start_scheduler
from database import init_db, migrate_db

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder=os.path.join(_HERE, "templates"),
    static_folder=os.path.join(_HERE, "static") if os.path.isdir(os.path.join(_HERE, "static")) else None,
)
CORS(app, supports_credentials=True)
app.secret_key         = os.environ.get("FLASK_SECRET_KEY", "inv-checker-dev-only-key")
app.permanent_session_lifetime = timedelta(hours=8)

# ── Blueprints ────────────────────────────────────────────────────────────────
app.register_blueprint(auth_bp)       # /api/auth/*  — must be first
app.register_blueprint(settings_bp)
app.register_blueprint(check_bp)
app.register_blueprint(zalora_bp)
app.register_blueprint(util_bp)
app.register_blueprint(db_bp)
app.register_blueprint(shopee_bp)
app.register_blueprint(lazada_bp)
app.register_blueprint(unified_bp)

# ── Global 401 handler — tells the frontend to show the login screen ──────────
@app.errorhandler(401)
def unauthorized(e):
    return jsonify({"error": "Unauthorized", "login_required": True}), 401


_services_started = False


def _should_start_services() -> bool:
    """
    Start background services in:
    - normal python execution
    - flask run worker process
    Avoid duplicate start in Werkzeug reloader parent process.
    """
    if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
        return os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    return True


def start_services_once() -> None:
    global _services_started
    if _services_started:
        return
    if not _should_start_services():
        log.info("Skipping scheduler init in reloader parent process")
        return
    cleanup_old_jobs()
    init_db()
    migrate_db()
    start_scheduler()
    _services_started = True
    log.info("Background services initialized (DB + scheduler)")


# Ensure scheduler starts even when launched via `flask run`.
start_services_once()

# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start_services_once()
    log.info("Inventory Checker — http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)