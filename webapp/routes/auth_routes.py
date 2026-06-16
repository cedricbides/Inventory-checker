"""
routes/auth_routes.py — login, logout, user management.

Roles:
  admin — full access + can manage users
  user  — full access except user management

Endpoints:
  POST /api/auth/login
  POST /api/auth/logout
  GET  /api/auth/me
  POST /api/auth/change-password

  GET    /api/users          (admin only)
  POST   /api/users          (admin only)
  PUT    /api/users/<id>     (admin only)
  DELETE /api/users/<id>     (admin only)
"""

import hashlib
import logging
import time
from collections import defaultdict
from functools import wraps

from flask import Blueprint, jsonify, request, session

from database import get_db
from helpers import write_audit

log = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

# ── Brute-force protection ─────────────────────────────────────────────────────
# Tracks failed attempts per IP: { ip: {"count": int, "locked_until": float} }
_fail_tracker: dict = defaultdict(lambda: {"count": 0, "locked_until": 0.0})

MAX_ATTEMPTS  = 5       # failed attempts before lockout
LOCKOUT_SECS  = 300     # 5 minutes lockout
WINDOW_SECS   = 600     # reset attempt count after 10 minutes of no failures

def _get_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

def _check_rate_limit(ip: str):
    """Returns (blocked: bool, seconds_remaining: int)."""
    rec = _fail_tracker[ip]
    now = time.time()
    if rec["locked_until"] > now:
        return True, int(rec["locked_until"] - now)
    return False, 0

def _record_fail(ip: str):
    rec = _fail_tracker[ip]
    now = time.time()
    rec["count"] += 1
    if rec["count"] >= MAX_ATTEMPTS:
        rec["locked_until"] = now + LOCKOUT_SECS
        rec["count"] = 0
        log.warning("Login locked for IP %s (%ds)", ip, LOCKOUT_SECS)

def _clear_fail(ip: str):
    _fail_tracker.pop(ip, None)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def login_required(f):
    """Returns 401 if not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Returns 403 if not an admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Auth ───────────────────────────────────────────────────────────────────────

@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    ip       = _get_ip()
    blocked, secs = _check_rate_limit(ip)
    if blocked:
        log.warning("Blocked login attempt from %s (%ds remaining)", ip, secs)
        return jsonify({"error": f"Too many failed attempts. Try again in {secs} seconds."}), 429

    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, full_name, permissions FROM users WHERE username = ?",
            (username,)
        ).fetchone()

    if not row or row["password_hash"] != _hash(password):
        _record_fail(ip)
        write_audit("login_failed", {"username": username, "ip": ip})
        log.warning("Failed login: %s from %s", username, ip)
        # Generic message — don't reveal whether username exists
        return jsonify({"error": "Invalid username or password"}), 401

    _clear_fail(ip)

    # Update last_login
    with get_db() as conn:
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (row["id"],))
        conn.commit()

    session["logged_in"]   = True
    session["user_id"]     = row["id"]
    session["username"]    = row["username"]
    session["role"]        = row["role"]
    session["full_name"]   = row["full_name"]
    session["permissions"] = row["permissions"] or "[]"
    session.permanent      = True

    write_audit("login", {"username": username, "role": row["role"]})
    log.info("Login: %s (%s)", username, row["role"])

    return jsonify({                                                                                                                                                                                                                        
        "ok":          True,
        "username":    row["username"],
        "full_name":   row["full_name"],
        "role":        row["role"],
        "permissions": row["permissions"] or "[]",
    })


@auth_bp.route("/api/auth/logout", methods=["POST"])
def api_logout():
    username = session.get("username", "")
    session.clear()
    write_audit("logout", {"username": username})
    return jsonify({"ok": True})


@auth_bp.route("/api/auth/me")
def api_me():
    if session.get("logged_in"):
        return jsonify({
            "logged_in":   True,
            "username":    session.get("username", ""),
            "full_name":   session.get("full_name", ""),
            "role":        session.get("role", "user"),
            "permissions": session.get("permissions", "[]"),
        })
    return jsonify({"logged_in": False}), 401


@auth_bp.route("/api/auth/change-password", methods=["POST"])
@login_required
def api_change_password():
    data         = request.get_json(force=True)
    current      = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    username     = session.get("username", "")

    with get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()

    if not row or row["password_hash"] != _hash(current):
        return jsonify({"error": "Current password is incorrect"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400

    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (_hash(new_password), username)
        )
        conn.commit()

    write_audit("password_changed", {"username": username})
    return jsonify({"ok": True})


# ── User Management (admin only) ───────────────────────────────────────────────

@auth_bp.route("/api/users", methods=["GET"])
@admin_required
def api_list_users():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, role, full_name, permissions, created_at, last_login FROM users ORDER BY id"
        ).fetchall()
    return jsonify({"users": [dict(r) for r in rows]})


@auth_bp.route("/api/users", methods=["POST"])
@admin_required
def api_create_user():
    data      = request.get_json(force=True)
    username  = (data.get("username") or "").strip()
    password  = data.get("password") or ""
    role      = data.get("role", "user")
    full_name = (data.get("full_name") or "").strip()
    import json
    permissions = json.dumps(data.get("permissions") or [])

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
    if role not in ("admin", "user"):
        return jsonify({"error": "Role must be admin or user"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, full_name, permissions) VALUES (?,?,?,?,?)",
                (username, _hash(password), role, full_name, permissions)
            )
            conn.commit()
    except Exception:
        return jsonify({"error": f"Username '{username}' already exists"}), 409

    write_audit("user_created", {"username": username, "role": role, "by": session.get("username")})
    return jsonify({"ok": True})


@auth_bp.route("/api/users/<int:user_id>", methods=["PUT"])
@admin_required
def api_update_user(user_id: int):
    data      = request.get_json(force=True)
    role      = data.get("role")
    full_name = data.get("full_name")
    password  = data.get("password")
    import json
    permissions = data.get("permissions")  # list or None

    with get_db() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404

        if role and role not in ("admin", "user"):
            return jsonify({"error": "Role must be admin or user"}), 400

        if role:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        if full_name is not None:
            conn.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user_id))
        if password:
            if len(password) < 6:
                return jsonify({"error": "Password must be at least 6 characters"}), 400
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash(password), user_id))
        if permissions is not None:
            conn.execute("UPDATE users SET permissions = ? WHERE id = ?", (json.dumps(permissions), user_id))
        conn.commit()

    write_audit("user_updated", {"user_id": user_id, "by": session.get("username")})
    return jsonify({"ok": True})


@auth_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@admin_required
def api_delete_user(user_id: int):
    # Prevent deleting yourself
    if user_id == session.get("user_id"):
        return jsonify({"error": "Cannot delete your own account"}), 400

    with get_db() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

    write_audit("user_deleted", {"user_id": user_id, "by": session.get("username")})
    return jsonify({"ok": True})