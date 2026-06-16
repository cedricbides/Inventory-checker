"""
routes/settings_routes.py — all /api/settings/* endpoints.

Covers:
  • GET  /api/settings              full settings (secrets masked)
  • POST /api/settings/marketplace
  • PUT  /api/settings/marketplace/<id>
  • DEL  /api/settings/marketplace/<id>
  • POST /api/settings/marketplace/<id>/test
  • PATCH /api/settings/marketplace/<id>/status
  • GET  /api/settings/ordazzle
  • PUT  /api/settings/ordazzle
  • GET  /api/settings/sap
  • PUT  /api/settings/sap
  • POST /api/settings/warehouse
  • PUT  /api/settings/warehouse/<id>
  • DEL  /api/settings/warehouse/<id>
  • GET  /api/settings/threshold         
  • PUT  /api/settings/threshold         
  • GET  /api/settings/schedules        
  • POST /api/settings/schedules        
  • PUT  /api/settings/schedules/<mp_id> 
  • DEL  /api/settings/schedules/<mp_id> 

Every mutation calls write_audit() so there is a persistent record of who
changed what and when.
"""

import logging
import uuid
from routes.auth_routes import login_required

import requests as _requests
from flask import Blueprint, jsonify, request

from helpers import (
    MARKETPLACE_FIELDS, MARKETPLACE_LABELS,
    load_settings, save_settings,
    resolve_warehouse,
    write_audit,
)

log = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mask_marketplace_secrets(mp: dict) -> dict:
    """Return a copy of a marketplace dict with secret fields replaced by ••••."""
    safe = dict(mp)
    for field in ("partner_key", "app_secret", "access_token", "client_secret"):
        if field in safe:
            safe[field] = "••••••••" if safe[field] else ""
    return safe


def _mask_system(d: dict) -> dict:
    masked = dict(d)
    if masked.get("password"):
        masked["password"] = "••••••••"
    return masked


def _resolve_password_update(new_value: str, current_value: str) -> str:
    """Keep existing password when frontend sends masked placeholder."""
    return new_value if new_value and "••" not in new_value else current_value


# ══════════════════════════════════════════════════════════════════════════════
#  Full settings read
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings", methods=["GET"])
def api_get_settings():
    s  = load_settings()
    wh = s.get("warehouses", [])

    safe_mp = []
    for mp in s.get("marketplaces", []):
        mp_safe = _mask_marketplace_secrets(mp)
        resolved = resolve_warehouse(mp, wh)
        mp_safe["resolved_warehouse_code"] = resolved["code"] if resolved else ""
        mp_safe["resolved_warehouse_name"] = resolved["name"] if resolved else ""
        safe_mp.append(mp_safe)

    return jsonify({
        "schema_version":        s.get("schema_version", 1),
        "mismatch_threshold_pct": s.get("mismatch_threshold_pct", 10),
        "pull_schedules":        s.get("pull_schedules", []),
        "marketplaces":          safe_mp,
        "warehouses":            wh,
        "marketplace_fields":    MARKETPLACE_FIELDS,
        "marketplace_labels":    MARKETPLACE_LABELS,
        "ordazzle_system":       _mask_system(s.get("ordazzle_system", {})),
        "sap_system":            _mask_system(s.get("sap_system", {})),
        "shopify_system":        _mask_system(s.get("shopify_system", {})),
        "magento_system":        _mask_system(s.get("magento_system", {})),
    })


# ══════════════════════════════════════════════════════════════════════════════
#  Discrepancy threshold   (long-term: flag runs above this mismatch %)
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/threshold", methods=["GET"])
def api_get_threshold():
    s = load_settings()
    return jsonify({"mismatch_threshold_pct": s.get("mismatch_threshold_pct", 10)})


@login_required
@settings_bp.route("/api/settings/threshold", methods=["PUT"])
def api_set_threshold():
    data = request.get_json(force=True)
    try:
        pct = int(data.get("mismatch_threshold_pct", 10))
        if not (0 <= pct <= 100):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "mismatch_threshold_pct must be an integer 0–100"}), 400

    s = load_settings()
    old = s.get("mismatch_threshold_pct", 10)
    s["mismatch_threshold_pct"] = pct
    save_settings(s)
    write_audit("set_threshold", {"old": old, "new": pct})
    return jsonify({"ok": True, "mismatch_threshold_pct": pct})


# ══════════════════════════════════════════════════════════════════════════════
#  Pull schedules   (long-term: auto-schedule Zalora pulls)
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/schedules", methods=["GET"])
def api_list_schedules():
    s = load_settings()
    schedules = []
    for sc in s.get("pull_schedules", []):
        item = dict(sc)
        item.setdefault("func", "Zalora Inventory Pull")
        item.setdefault("interval_hours", 24)
        item.setdefault("enabled", True)
        schedules.append(item)
    return jsonify({"schedules": schedules})


@login_required
@settings_bp.route("/api/settings/schedules", methods=["POST"])
def api_add_schedule():
    """
    Body: { mp_id, interval_hours, enabled }
    Creates a new schedule entry.  One schedule per mp_id is enforced.
    """
    data = request.get_json(force=True)
    mp_id = (data.get("mp_id") or "").strip()
    if not mp_id:
        return jsonify({"error": "mp_id is required"}), 400
    try:
        interval_hours = float(data.get("interval_hours", 24))
        if interval_hours <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "interval_hours must be a positive number"}), 400

    s = load_settings()
    # Verify the marketplace exists
    mp = next((m for m in s.get("marketplaces", []) if m["id"] == mp_id), None)
    if not mp:
        return jsonify({"error": "Marketplace not found"}), 404
    if mp.get("type") != "zalora":
        return jsonify({"error": "Auto-pull is currently supported for Zalora only"}), 400

    # Deduplicate — one schedule per (mp_id, func)
    func_name = (data.get("func") or "Zalora Inventory Pull").strip()
    s["pull_schedules"] = [sc for sc in s.get("pull_schedules", []) if sc["mp_id"] != mp_id]
    new_sched = {
        "mp_id":          mp_id,
        "func":           func_name,
        "brand":          mp.get("brand", ""),
        "interval_hours": interval_hours,
        "enabled":        bool(data.get("enabled", True)),
        "last_run":       "",
    }
    s["pull_schedules"].append(new_sched)
    save_settings(s)
    write_audit("add_schedule", new_sched)
    log.info("Pull schedule added: mp_id=%s every %.1fh", mp_id, interval_hours)
    return jsonify({"ok": True, "schedule": new_sched})


@login_required
@settings_bp.route("/api/settings/schedules/<mp_id>", methods=["PUT"])
def api_update_schedule(mp_id: str):
    data = request.get_json(force=True)
    s    = load_settings()
    for sched in s.get("pull_schedules", []):
        if sched["mp_id"] == mp_id:
            if "interval_hours" in data:
                try:
                    h = float(data["interval_hours"])
                    if h <= 0:
                        raise ValueError
                    sched["interval_hours"] = h
                except (TypeError, ValueError):
                    return jsonify({"error": "interval_hours must be a positive number"}), 400
            if "enabled" in data:
                sched["enabled"] = bool(data["enabled"])
            if "func" in data and str(data["func"]).strip():
                sched["func"] = str(data["func"]).strip()
            save_settings(s)
            write_audit("update_schedule", {"mp_id": mp_id, "changes": data})
            return jsonify({"ok": True, "schedule": sched})
    return jsonify({"error": "Schedule not found"}), 404


@login_required
@settings_bp.route("/api/settings/schedules/<mp_id>", methods=["DELETE"])
def api_delete_schedule(mp_id: str):
    s      = load_settings()
    before = len(s.get("pull_schedules", []))
    s["pull_schedules"] = [sc for sc in s.get("pull_schedules", []) if sc["mp_id"] != mp_id]
    if len(s["pull_schedules"]) == before:
        return jsonify({"error": "Schedule not found"}), 404
    save_settings(s)
    write_audit("delete_schedule", {"mp_id": mp_id})
    return jsonify({"ok": True})


@login_required
@settings_bp.route("/api/settings/schedules/cleanup", methods=["POST"])
def api_cleanup_schedules():
    """
    Remove orphan/invalid schedules:
    - mp_id missing
    - marketplace no longer exists
    - non-zalora schedules (current scheduler scope)
    Returns removed list so UI can show what was cleaned.
    """
    s = load_settings()
    mp_map = {m.get("id"): m for m in s.get("marketplaces", [])}
    cleaned = []
    kept = []
    for sc in s.get("pull_schedules", []):
        mp_id = sc.get("mp_id")
        mp = mp_map.get(mp_id)
        invalid = (
            not mp_id
            or mp is None
            or (mp.get("type") != "zalora")
        )
        if invalid:
            cleaned.append(sc)
        else:
            kept.append(sc)

    s["pull_schedules"] = kept
    save_settings(s)
    write_audit("cleanup_schedules", {"removed": len(cleaned)})
    return jsonify({"ok": True, "removed": len(cleaned), "removed_items": cleaned})


# ══════════════════════════════════════════════════════════════════════════════
#  Marketplaces
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/marketplace", methods=["POST"])
def api_add_marketplace():
    data    = request.get_json(force=True)
    mp_type = data.get("type", "").lower()
    if mp_type not in MARKETPLACE_FIELDS:
        return jsonify({"error": f"Unknown marketplace type '{mp_type}'"}), 400

    s      = load_settings()
    new_mp = {
        "id":             str(uuid.uuid4()),
        "type":           mp_type,
        "label":          MARKETPLACE_LABELS.get(mp_type, mp_type),
        "name":           data.get("name", "").strip() or MARKETPLACE_LABELS.get(mp_type),
        "brand":          data.get("brand", "").strip(),
        "region":         data.get("region", "PH").strip(),
        "warehouse_node": data.get("warehouse_node", "").strip(),
        "status":         "connected",
    }
    for field in MARKETPLACE_FIELDS[mp_type]:
        new_mp[field] = data.get(field, "").strip()

    s["marketplaces"].append(new_mp)
    save_settings(s)
    write_audit("add_marketplace", {"name": new_mp["name"], "type": mp_type, "brand": new_mp["brand"]})
    log.info("Added marketplace: %s (%s) brand=%s", new_mp["name"], mp_type, new_mp["brand"])
    return jsonify({"ok": True, "id": new_mp["id"]})


@login_required
@settings_bp.route("/api/settings/marketplace/<mp_id>", methods=["PUT"])
def api_update_marketplace(mp_id: str):
    data = request.get_json(force=True)
    s    = load_settings()
    for mp in s["marketplaces"]:
        if mp["id"] == mp_id:
            mp["name"]   = data.get("name",   mp["name"])
            mp["brand"]  = data.get("brand",  mp["brand"])
            mp["region"] = data.get("region", mp.get("region", "PH"))
            if "warehouse_node" in data:
                mp["warehouse_node"] = data.get("warehouse_node", "").strip()
            for field in MARKETPLACE_FIELDS.get(mp["type"], []):
                v = data.get(field, "")
                if v and "••" not in v:
                    mp[field] = v
            save_settings(s)
            write_audit("update_marketplace", {"id": mp_id, "name": mp["name"]})
            return jsonify({"ok": True})
    return jsonify({"error": "Marketplace not found"}), 404


@login_required
@settings_bp.route("/api/settings/marketplace/<mp_id>", methods=["DELETE"])
def api_delete_marketplace(mp_id: str):
    s = load_settings()
    # Capture name before deletion for the audit entry
    mp_name = next((m["name"] for m in s["marketplaces"] if m["id"] == mp_id), mp_id)
    before  = len(s["marketplaces"])
    s["marketplaces"] = [m for m in s["marketplaces"] if m["id"] != mp_id]
    if len(s["marketplaces"]) == before:
        return jsonify({"error": "Not found"}), 404
    # Also remove any associated schedule
    s["pull_schedules"] = [sc for sc in s.get("pull_schedules", []) if sc["mp_id"] != mp_id]
    save_settings(s)
    write_audit("delete_marketplace", {"id": mp_id, "name": mp_name})
    log.info("Deleted marketplace: %s (%s)", mp_name, mp_id)
    return jsonify({"ok": True})


@login_required
@settings_bp.route("/api/settings/marketplace/<mp_id>/test", methods=["POST"])
def api_test_marketplace(mp_id: str):
    s  = load_settings()
    mp = next((m for m in s["marketplaces"] if m["id"] == mp_id), None)
    if not mp:
        return jsonify({"error": "Not found"}), 404
    mp_type = mp.get("type")
    try:
        if mp_type == "zalora":
            r = _requests.post(
                "https://sellercenter-api.zalora.com.ph/oauth/client-credentials",
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     mp.get("client_id", ""),
                    "client_secret": mp.get("client_secret", ""),
                },
                timeout=10,
            )
            if r.status_code == 200:
                return jsonify({"ok": True, "message": "Connected to Zalora ✓"})
            return jsonify({"ok": False, "message": f"Zalora returned HTTP {r.status_code}"}), 400
        else:
            return jsonify({
                "ok": True,
                "message": (
                    f"Credentials saved — live test for "
                    f"{MARKETPLACE_LABELS.get(mp_type, mp_type)} not yet implemented."
                ),
            })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
#  Ordazzle system
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/marketplace/<mp_id>/status", methods=["PATCH"])
def api_toggle_marketplace_status(mp_id: str):
    """
    Toggle a marketplace between connected and disconnected.
    Body: { "status": "connected" | "disconnected" }
    """
    data = request.get_json(force=True)
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in ("connected", "disconnected"):
        return jsonify({"error": "status must be 'connected' or 'disconnected'"}), 400

    s = load_settings()
    for mp in s["marketplaces"]:
        if mp["id"] == mp_id:
            old_status = mp.get("status", "unknown")
            mp["status"] = new_status
            save_settings(s)
            write_audit(
                "update_marketplace_status",
                {"id": mp_id, "name": mp["name"], "old": old_status, "new": new_status},
            )
            log.info("Marketplace %s (%s) status: %s → %s", mp["name"], mp_id, old_status, new_status)
            return jsonify({"ok": True, "status": new_status})
    return jsonify({"error": "Marketplace not found"}), 404


# ══════════════════════════════════════════════════════════════════════════════
#  Ordazzle system
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/ordazzle", methods=["GET"])
def api_get_ordazzle():
    s = load_settings()
    return jsonify({"ordazzle_system": _mask_system(s.get("ordazzle_system", {}))})


@login_required
@settings_bp.route("/api/settings/ordazzle", methods=["PUT"])
def api_update_ordazzle():
    data    = request.get_json(force=True)
    s       = load_settings()
    current = s.get("ordazzle_system", {})
    new_pwd = data.get("password", "")
    s["ordazzle_system"] = {
        "base_url": data.get("base_url", current.get("base_url", "")).strip(),
        "username": data.get("username", current.get("username", "")).strip(),
        "password": _resolve_password_update(new_pwd, current.get("password", "")),
        "enabled":  bool(data.get("enabled", current.get("enabled", False))),
    }
    save_settings(s)
    write_audit("update_ordazzle_system", {"base_url": s["ordazzle_system"]["base_url"]})
    log.info("Ordazzle system updated: base_url=%s", s["ordazzle_system"]["base_url"])
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
#  SAP system
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/sap", methods=["GET"])
def api_get_sap():
    s = load_settings()
    return jsonify({"sap_system": _mask_system(s.get("sap_system", {}))})


@login_required
@settings_bp.route("/api/settings/sap", methods=["PUT"])
def api_update_sap():
    data    = request.get_json(force=True)
    s       = load_settings()
    current = s.get("sap_system", {})
    new_pwd = data.get("password", "")
    s["sap_system"] = {
        "server_url": data.get("server_url", current.get("server_url", "")).strip(),
        "client":     data.get("client",     current.get("client", "")).strip(),
        "username":   data.get("username",   current.get("username", "")).strip(),
        "password":   _resolve_password_update(new_pwd, current.get("password", "")),
        "enabled":    bool(data.get("enabled", current.get("enabled", False))),
    }
    save_settings(s)
    write_audit("update_sap_system", {})
    log.info("SAP system updated")
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
#  Shopify system
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/shopify", methods=["GET"])
def api_get_shopify():
    s = load_settings()
    return jsonify({"shopify_system": _mask_system(s.get("shopify_system", {}))})


@login_required
@settings_bp.route("/api/settings/shopify", methods=["PUT"])
def api_update_shopify():
    data    = request.get_json(force=True)
    s       = load_settings()
    current = s.get("shopify_system", {})
    new_token = data.get("access_token", "")
    s["shopify_system"] = {
        "store_domain": data.get("store_domain", current.get("store_domain", "")).strip(),
        "access_token": _resolve_password_update(new_token, current.get("access_token", "")),
        "enabled":      bool(data.get("enabled", current.get("enabled", False))),
    }
    save_settings(s)
    write_audit("update_shopify_system", {"store_domain": s["shopify_system"]["store_domain"]})
    log.info("Shopify system updated: store_domain=%s", s["shopify_system"]["store_domain"])
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
#  Magento system
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/magento", methods=["GET"])
def api_get_magento():
    s = load_settings()
    return jsonify({"magento_system": _mask_system(s.get("magento_system", {}))})


@login_required
@settings_bp.route("/api/settings/magento", methods=["PUT"])
def api_update_magento():
    data    = request.get_json(force=True)
    s       = load_settings()
    current = s.get("magento_system", {})
    new_token = data.get("access_token", "")
    s["magento_system"] = {
        "store_url":    data.get("store_url", current.get("store_url", "")).strip(),
        "access_token": _resolve_password_update(new_token, current.get("access_token", "")),
        "enabled":      bool(data.get("enabled", current.get("enabled", False))),
    }
    save_settings(s)
    write_audit("update_magento_system", {"store_url": s["magento_system"]["store_url"]})
    log.info("Magento system updated: store_url=%s", s["magento_system"]["store_url"])
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
#  Warehouses
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@settings_bp.route("/api/settings/warehouse", methods=["POST"])
def api_add_warehouse():
    data  = request.get_json(force=True)
    s     = load_settings()
    new_wh = {
        "id":          str(uuid.uuid4()),
        "name":        data.get("name", "").strip(),
        "code":        data.get("code", "").strip(),
        "sap_site":    data.get("sap_site", "").strip(),
        "storage_loc": data.get("storage_loc", "0002").strip(),
        "brands":      [b.strip() for b in data.get("brands", []) if b.strip()],
    }
    if not new_wh["name"] or not new_wh["code"]:
        return jsonify({"error": "name and code are required"}), 400
    s["warehouses"].append(new_wh)
    save_settings(s)
    write_audit("add_warehouse", {"name": new_wh["name"], "code": new_wh["code"]})
    return jsonify({"ok": True, "id": new_wh["id"]})


@login_required
@settings_bp.route("/api/settings/warehouse/<wh_id>", methods=["PUT"])
def api_update_warehouse(wh_id: str):
    data = request.get_json(force=True)
    s    = load_settings()
    for wh in s["warehouses"]:
        if wh["id"] == wh_id:
            wh["name"]        = data.get("name",        wh["name"])
            wh["code"]        = data.get("code",        wh["code"])
            wh["sap_site"]    = data.get("sap_site",    wh.get("sap_site", ""))
            wh["storage_loc"] = data.get("storage_loc", wh.get("storage_loc", "0002"))
            if "brands" in data:
                wh["brands"] = [b.strip() for b in data["brands"] if b.strip()]
            save_settings(s)
            write_audit("update_warehouse", {"id": wh_id, "name": wh["name"]})
            return jsonify({"ok": True})
    return jsonify({"error": "Warehouse not found"}), 404


@login_required
@settings_bp.route("/api/settings/warehouse/<wh_id>", methods=["DELETE"])
def api_delete_warehouse(wh_id: str):
    s       = load_settings()
    wh_name = next((w["name"] for w in s["warehouses"] if w["id"] == wh_id), wh_id)
    before  = len(s["warehouses"])
    s["warehouses"] = [w for w in s["warehouses"] if w["id"] != wh_id]
    if len(s["warehouses"]) == before:
        return jsonify({"error": "Not found"}), 404
    save_settings(s)
    write_audit("delete_warehouse", {"id": wh_id, "name": wh_name})
    return jsonify({"ok": True})