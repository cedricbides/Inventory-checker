"""
helpers.py — shared state, paths, settings I/O, audit log, job helpers.
Imported by every route module and the scheduler.

Handles four long-term concerns:
  1. Schema version  — _migrate() upgrades old settings.json automatically.
  2. Atomic writes   — save_settings() uses .tmp + os.replace() so a crash
                       mid-write can never corrupt settings.json.
  3. Audit log       — write_audit() persists every mutation to audit_log.json.
  4. Paths           — _HERE/_ROOT kept here so every module shares them.
"""

import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime

# ── Path setup (must run before any inventory_pkg import) ─────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

log = logging.getLogger(__name__)

# ── File paths ─────────────────────────────────────────────────────────────────
SETTINGS_FILE     = os.path.join(_HERE, "settings.json")
PULL_HISTORY_FILE = os.path.join(_HERE, "pull_history.json")
AUDIT_LOG_FILE    = os.path.join(_HERE, "audit_log.json")
SCHEDULED_DIR     = os.path.join(_HERE, "scheduled_pulls")
JOBS_DIR          = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "inv_checker_jobs")
JOB_MAX_AGE_SECS  = 3600

# ── Marketplace constants ──────────────────────────────────────────────────────
MARKETPLACE_FIELDS = {
    "shopee":  ["partner_id", "partner_key", "shop_id", "access_token"],
    "lazada":  ["app_key", "app_secret", "access_token"],
    "tiktok":  ["app_key", "app_secret", "shop_id", "access_token"],
    "zalora":  ["client_id", "client_secret"],
    "shopify": ["store_domain", "access_token"],
}

MARKETPLACE_LABELS = {
    "shopee":  "Shopee",
    "lazada":  "Lazada",
    "tiktok":  "TikTok Shop",
    "zalora":  "Zalora",
    "shopify": "Shopify",
}

ORDAZZLE_SYSTEM_FIELDS = ["base_url", "username", "password"]
SAP_SYSTEM_FIELDS      = ["server_url", "client", "username", "password"]
SHOPIFY_SYSTEM_FIELDS  = ["store_domain", "access_token"]
MAGENTO_SYSTEM_FIELDS  = ["store_url", "access_token"]

# ── Schema ─────────────────────────────────────────────────────────────────────
SCHEMA_VERSION = 1


def _default_settings() -> dict:
    return {
        "schema_version":        SCHEMA_VERSION,
        "mismatch_threshold_pct": 10,
        "pull_schedules":        [],
        "marketplaces":          [],
        "ordazzle_system": {
            "base_url": "", "username": "", "password": "", "enabled": False,
        },
        "sap_system": {
            "server_url": "", "client": "", "username": "", "password": "",
            "enabled": False,
        },
        "shopify_system": {
            "store_domain": "", "access_token": "", "enabled": False,
        },
        "magento_system": {
            "store_url": "", "access_token": "", "enabled": False,
        },
        "warehouses": [
            {
                "id":          "wh-ssiebg",
                "name":        "SSIEBG Warehouse",
                "code":        "SSIEBG_WH_EBGWarehouse",
                "sap_site":    "2W06",
                "storage_loc": "0002",
                "brands": [
                    "Springfield", "Cortefiel", "MakeRoom", "MakeRoom & More",
                    "DKNY", "Dune London", "Pazzion", "Macarena", "Nine West",
                    "Polo Ralph Lauren", "Pomelo", "Lacoste", "women'secret",
                    "womensecret", "Lush", "Calvin Klein", "Tommy Hilfiger",
                    "Clarks", "Superga", "FFW",
                ],
            },
            {
                "id":          "wh-payless",
                "name":        "Payless Warehouse",
                "code":        "Payless_WH_Warehouse",
                "sap_site":    "30W9",
                "storage_loc": "0002",
                "brands":      ["Payless", "Payless ShoeSource", "Payless Shoes"],
            },
            {
                "id":          "wh-slci",
                "name":        "SLCI Warehouse",
                "code":        "SLCI_WH_Warehouse",
                "sap_site":    "36W2",
                "storage_loc": "0002",
                "brands":      ["Old Navy", "Gap", "Banana", "Banana Republic"],
            },
        ],
    }


def _migrate(s: dict) -> dict:
    """
    Upgrade a settings dict from an older schema version in-place.
    Each vN→vN+1 block adds missing keys with safe defaults so old files
    are never left with unknown key errors.
    """
    v = s.get("schema_version", 0)

    if v < 1:
        s.setdefault("mismatch_threshold_pct", 10)
        s.setdefault("pull_schedules", [])
        s["schema_version"] = 1
        log.info("Migrated settings.json: v0 → v1 (added threshold + pull_schedules)")

    # Future migrations go here:
    # if v < 2:
    #     s.setdefault("new_field", default_value)
    #     s["schema_version"] = 2

    return s


def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        s = _default_settings()
        save_settings(s)
        return s
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f)
        changed = s.get("schema_version", 0) < SCHEMA_VERSION
        s = _migrate(s)
        if changed:
            save_settings(s)
        return s
    except Exception as e:
        log.error("Failed to load settings.json: %s — using defaults", e)
        return _default_settings()


def save_settings(s: dict) -> None:
    """
    Atomic write: dump to <file>.tmp then os.replace() in one syscall.
    A crash or power-cut between the two lines leaves the .tmp file behind
    (harmless) rather than a half-written settings.json.
    """
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


# ── Warehouse helpers ──────────────────────────────────────────────────────────

def warehouse_for_brand(brand: str, warehouses: list) -> dict | None:
    bl = brand.lower()
    for wh in warehouses:
        for b in wh.get("brands", []):
            if b.lower() == bl or b.lower() in bl or bl in b.lower():
                return wh
    return None


def resolve_warehouse(mp: dict, warehouses: list) -> dict | None:
    brand = (mp.get("brand") or "").strip()
    wh = warehouse_for_brand(brand, warehouses)
    if wh:
        return wh
    code = (mp.get("warehouse_node") or "").strip()
    if code:
        return next((w for w in warehouses if w.get("code") == code), None)
    return None


# ── Job helpers ────────────────────────────────────────────────────────────────

def cleanup_old_jobs() -> None:
    if not os.path.isdir(JOBS_DIR):
        return
    cutoff = time.time() - JOB_MAX_AGE_SECS
    for entry in os.scandir(JOBS_DIR):
        if entry.is_dir() and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry.path, ignore_errors=True)


def job_dir(job_id: str) -> str:
    return os.path.join(JOBS_DIR, job_id)


def save_state(job_id: str, state: dict) -> None:
    with open(os.path.join(job_dir(job_id), "state.json"), "w") as f:
        json.dump(state, f)


def load_state(job_id: str) -> dict:
    with open(os.path.join(job_dir(job_id), "state.json")) as f:
        return json.load(f)


def save_upload(job_id: str, file_obj, filename: str) -> str:
    dest = os.path.join(job_dir(job_id), filename)
    file_obj.save(dest)
    return dest


def token_file_path(job_id: str) -> str:
    return os.path.join(job_dir(job_id), "dl_token.txt")


def download_info_path(job_id: str) -> str:
    return os.path.join(job_dir(job_id), "results", "download.json")


def is_download_token_valid(job_id: str, token: str) -> bool | None:
    """
    Return True when token matches, False when mismatched, None when missing.
    """
    try:
        with open(token_file_path(job_id)) as f:
            return f.read().strip() == token
    except FileNotFoundError:
        return None


def load_download_info(job_id: str) -> dict:
    with open(download_info_path(job_id)) as f:
        return json.load(f)


# ── JSON persistence helpers ───────────────────────────────────────────────────

def _atomic_append_json(filepath: str, entry: dict, encoding: str = "utf-8") -> None:
    """
    Load a JSON list from filepath, append entry, and write back atomically.

    This is the single implementation of the load-append-replace pattern that
    was previously duplicated in both append_pull_history and write_audit.
    Never raises — callers handle their own logging on failure.
    """
    entries = []
    if os.path.exists(filepath):
        with open(filepath, encoding=encoding) as f:
            entries = json.load(f)
    entries.append(entry)
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding=encoding) as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, filepath)


# ── Pull history ───────────────────────────────────────────────────────────────

def append_pull_history(entry: dict) -> None:
    try:
        _atomic_append_json(PULL_HISTORY_FILE, entry)
    except Exception as e:
        log.warning("Could not save pull history: %s", e)


# ── Audit log ──────────────────────────────────────────────────────────────────

def write_audit(action: str, detail: dict | None = None) -> None:
    """
    Append one structured entry to audit_log.json.
    Never raises — a logging failure must never break a user-facing request.

    Called from every route that mutates settings (add/edit/delete marketplace,
    warehouse, system settings) and from the scheduler for auto-pulls.
    """
    try:
        ip = "scheduler"
        try:
            from flask import request as _req
            if _req:
                ip = _req.remote_addr or "unknown"
        except RuntimeError:
            pass  # no request context (called from scheduler thread)

        _atomic_append_json(AUDIT_LOG_FILE, {
            "ts":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "ip":     ip,
            "detail": detail or {},
        })
    except Exception as exc:
        log.warning("audit_log write failed (%s): %s", action, exc)