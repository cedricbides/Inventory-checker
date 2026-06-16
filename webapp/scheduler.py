"""
scheduler.py — background scheduler for all read-only pull jobs.

How it works
------------
APScheduler fires _tick() every minute.  _tick() loads pull_schedules from
settings.json and fires a background thread for any schedule that is:
  • enabled == true
  • last_run is absent, or now - last_run >= interval_hours

Each job is dispatched by its `func` field (the SCHED_FUNCTIONS label) to
the correct reader module.  All dispatched functions are READ ONLY —
they fetch data and save a CSV; they never write back to any marketplace.

Supported functions (READ ONLY)
--------------------------------
  Zalora
  ------
  Inventory Sync Zalora           → zalora_pull.do_pull()
  Zalora Get Autoship Order       → zalora_reader.get_autoship_orders()
  Zalora Get Order Reco           → zalora_reader.get_order_reco()
  Zalora Get Payout               → zalora_reader.get_payout()
  Zalora Product QC Status update → zalora_reader.get_qc_status()

  Shopee
  ------
  Shopee Get Orders               → shopee_reader.get_orders()
  Shopee Inventory Sync           → shopee_reader.get_inventory()

  Lazada
  ------
  Lazada Get Orders               → lazada_reader.get_orders()
  Lazada Inventory Sync           → lazada_reader.get_inventory()

  Ordazzle
  --------
  Ordazzle Export SSI EBG         → ordazzle_reader.export_ssi_ebg()
  Ordazzle Export SLCI            → ordazzle_reader.export_slci()
  Ordazzle SAP Order Sync         → ordazzle_reader.sap_order_sync()
"""

import csv
import io
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.base import BaseExecutor
from helpers import _HERE, append_pull_history, load_settings, write_audit
from reconciliation_jobs import (
    unified_inventory_import_job,
    discrepancy_engine_job,
    cleanup_job as run_cleanup_job,
)

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


# ── Dispatcher map ─────────────────────────────────────────────────────────────
# Maps SCHED_FUNCTIONS label → (channel_type, callable_key)
# channel_type: which credential block to look up ('zalora'|'shopee'|'lazada'|'ordazzle')
# callable_key: looked up in _READERS at runtime (late import keeps startup fast)

_DISPATCH: dict[str, tuple[str, str]] = {
    # ── Zalora ──
    "Zalora Inventory Pull":            ("zalora",    "inventory"),
    "Inventory Sync Zalora":            ("zalora",    "inventory"),  # backward compatibility
    "Zalora Get Autoship Order":        ("zalora",    "autoship_orders"),
    "Zalora Get Order Reco":            ("zalora",    "order_reco"),
    "Zalora Get Payout":                ("zalora",    "payout"),
    "Zalora Product QC Status update":  ("zalora",    "qc_status"),

    # ── Shopee ──
    "Shopee Get Orders":                ("shopee",    "orders"),
    "Shopee Inventory Sync":            ("shopee",    "inventory"),

    # ── Lazada ──
    "Lazada Get Orders":                ("lazada",    "orders"),
    "Lazada Inventory Sync":            ("lazada",    "inventory"),

    # ── Ordazzle ──
    "Ordazzle Export SSI EBG":          ("ordazzle",  "export_ssi_ebg"),
    "Ordazzle Export SLCI":             ("ordazzle",  "export_slci"),
    "Ordazzle SAP Order Sync":          ("ordazzle",  "sap_order_sync"),
}


def _get_reader(channel: str, key: str):
    """Late-import the correct reader function to keep startup fast."""
    if channel == "zalora":
        if key == "inventory":
            from zalora_pull import do_pull
            return do_pull
        from zalora_reader import (
            get_autoship_orders, get_order_reco, get_payout, get_qc_status
        )
        return {
            "autoship_orders": get_autoship_orders,
            "order_reco":      get_order_reco,
            "payout":          get_payout,
            "qc_status":       get_qc_status,
        }[key]

    if channel == "shopee":
        from shopee_reader import get_orders, get_inventory
        return {"orders": get_orders, "inventory": get_inventory}[key]

    if channel == "lazada":
        from lazada_reader import get_orders, get_inventory
        return {"orders": get_orders, "inventory": get_inventory}[key]

    if channel == "ordazzle":
        from ordazzle_reader import export_ssi_ebg, export_slci, sap_order_sync
        return {
            "export_ssi_ebg": export_ssi_ebg,
            "export_slci":    export_slci,
            "sap_order_sync": sap_order_sync,
        }[key]

    raise ValueError(f"Unknown channel: {channel}")


# ── CSV save helper ────────────────────────────────────────────────────────────

def _save_csv(rows: list[dict], label: str) -> tuple[str, str, str]:
    """
    Write rows to scheduled_pulls/ and also to a jobs/ folder.
    Returns (csv_path, job_id, download_url).
    """
    from helpers import SCHEDULED_DIR, job_dir, append_pull_history
    from inventory_pkg.utils import safe_filename

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8-sig")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename  = f"{safe_filename(label)}_{timestamp}.csv"

    # Scheduled pulls folder (persists)
    os.makedirs(SCHEDULED_DIR, exist_ok=True)
    csv_path = os.path.join(SCHEDULED_DIR, filename)
    with open(csv_path, "wb") as fh:
        fh.write(csv_bytes)

    # Job folder so /api/zalora/download still works
    jid      = str(uuid.uuid4())
    dl_token = str(uuid.uuid4())
    dl_dir   = os.path.join(job_dir(jid), "results")
    os.makedirs(dl_dir, exist_ok=True)
    dl_path  = os.path.join(dl_dir, filename)
    with open(dl_path, "wb") as fh:
        fh.write(csv_bytes)
    with open(os.path.join(dl_dir, "download.json"), "w") as fh:
        _json.dump({"type": "csv", "filename": filename, "path": dl_path}, fh)
    with open(os.path.join(job_dir(jid), "dl_token.txt"), "w") as fh:
        fh.write(dl_token)

    download_url = f"/api/zalora/download/{jid}/{dl_token}"
    return csv_path, jid, download_url


# ── Core job runner ────────────────────────────────────────────────────────────

def _run_job(sched: dict) -> None:
    """
    Execute one scheduled read-only job end-to-end.
    Called in a daemon thread from _tick().
    """
    from helpers import (
        load_settings, save_settings,
        append_pull_history, write_audit,
    )
    from database import get_db

    # Backward-compatible default for older schedule entries without func.
    func_name = (sched.get("func") or "Zalora Inventory Pull").strip()
    mp_id     = sched.get("mp_id", "")

    log.info("Scheduler: starting job '%s' mp_id=%s", func_name, mp_id)

    try:
        channel, key = _DISPATCH[func_name]
    except KeyError:
        log.warning("Scheduler: unknown function '%s' — skipped", func_name)
        return

    settings = load_settings()
    reader   = _get_reader(channel, key)

    try:
        # ── Ordazzle jobs: pass ordazzle_system cfg, no mp needed ─────────────
        if channel == "ordazzle":
            cfg  = settings.get("ordazzle_system") or {}
            rows = reader(cfg)
            label = f"Ordazzle_{key}"
            brand = "Ordazzle"

        # ── Marketplace jobs: resolve mp dict ─────────────────────────────────
        else:
            mp = next(
                (m for m in settings.get("marketplaces", [])
                 if m.get("id") == mp_id and m.get("type") == channel),
                None,
            )
            if not mp:
                log.warning(
                    "Scheduler: mp_id %s not found or wrong type (expected %s) — skipped",
                    mp_id, channel,
                )
                return

            brand = (mp.get("brand") or "").strip()
            rows  = reader(mp)
            label = f"{channel.title()}_{key}_{brand}"

        # ── Save CSV ──────────────────────────────────────────────────────────
        csv_path, jid, download_url = _save_csv(rows, label)

        # ── Update last_run ───────────────────────────────────────────────────
        settings = load_settings()
        for s in settings.get("pull_schedules", []):
            s_func = (s.get("func") or "Zalora Inventory Pull").strip()
            if (s_func == func_name and s.get("mp_id", "") == mp_id):
                # Normalize old schedule records so future ticks are reliable.
                s["func"] = s_func
                s["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_settings(settings)

        # ── Pull history + audit ──────────────────────────────────────────────
        append_pull_history({
            "pulled_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            "brand":        brand,
            "mp_id":        mp_id,
            "func":         func_name,
            "rows":         len(rows),
            "filename":     os.path.basename(csv_path),
            "path":         csv_path,
            "download_url": download_url,
            "scheduled":    True,
        })
        write_audit("scheduled_job_completed", {
            "func":     func_name,
            "mp_id":    mp_id,
            "brand":    brand,
            "rows":     len(rows),
            "file":     os.path.basename(csv_path),
        })
        try:
            with get_db() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET last_exec = ?, last_status = ?
                    WHERE lower(channel) = lower(?) AND lower(brand) = lower(?)
                    """,
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "success", channel.title(), brand),
                )
                conn.commit()
        except Exception:
            pass

        # Keep unified snapshot fresh after inventory pulls.
        # This remains read-only to external systems: it only writes internal DB.
        if key == "inventory" and channel in ("zalora", "shopee", "lazada"):
            try:
                import_result = unified_inventory_import_job()
                write_audit("scheduled_unified_refresh", {
                    "func": func_name,
                    "mp_id": mp_id,
                    "result": import_result,
                })
            except Exception as exc:
                log.warning("Scheduler: unified import after '%s' failed: %s", func_name, exc)

        log.info(
            "Scheduler: job '%s' done — brand=%s rows=%d → %s",
            func_name, brand, len(rows), os.path.basename(csv_path),
        )

    except Exception as exc:
        log.exception(
            "Scheduler: job '%s' FAILED for mp_id=%s: %s",
            func_name, mp_id, exc,
        )
        try:
            write_audit("scheduled_job_failed", {
                "func":  func_name,
                "mp_id": mp_id,
                "error": str(exc),
            })
            with get_db() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET last_exec = ?, last_status = ?
                    WHERE lower(channel) = lower(?) AND lower(brand) = lower(?)
                    """,
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "failed", channel.title() if "channel" in locals() else "", brand if "brand" in locals() else ""),
                )
                conn.commit()
        except Exception:
            pass


# ── Tick ───────────────────────────────────────────────────────────────────────

def _tick() -> None:
    """
    Called every minute by APScheduler.
    Exits immediately if no enabled schedules — safe when connected to prod.
    """
    global _scheduler
    if _scheduler is not None and not _scheduler.running:
        _scheduler = None
        return

    try:
        from helpers import load_settings
        raw_schedules = load_settings().get("pull_schedules", [])
        schedules = []
        for s in raw_schedules:
            # Normalize in-memory defaults so old JSON schema still runs.
            s2 = dict(s)
            s2["func"] = (s2.get("func") or "Zalora Inventory Pull").strip()
            s2["enabled"] = bool(s2.get("enabled", True))
            s2["interval_hours"] = float(s2.get("interval_hours", 24) or 24)
            if s2["enabled"]:
                schedules.append(s2)
        if not schedules:
            return  # nothing configured — do nothing, touch nothing

        now = datetime.now()
        for sched in schedules:
            func_name      = (sched.get("func") or "Zalora Inventory Pull").strip()
            mp_id          = sched.get("mp_id", "")
            interval_hours = float(sched.get("interval_hours", 24) or 24)
            last_run_str   = sched.get("last_run", "")

            if func_name not in _DISPATCH:
                log.debug("Scheduler: func '%s' not in dispatch map — skipped", func_name)
                continue

            if last_run_str:
                try:
                    last_run = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M")
                    if now - last_run < timedelta(hours=interval_hours):
                        continue   # not due yet
                except ValueError:
                    pass           # bad date string → treat as never run

            t = threading.Thread(
                target=_run_job,
                args=(sched,),
                daemon=True,
                name=f"job-{func_name[:20]}-{mp_id[:8]}",
            )
            t.start()
            log.info("Scheduler: triggered '%s' for mp_id=%s", func_name, mp_id)

    except RuntimeError as exc:
        log.debug("Scheduler tick suppressed after shutdown: %s", exc)
    except Exception as exc:
        log.warning("Scheduler _tick error: %s", exc)


# ── APScheduler setup ──────────────────────────────────────────────────────────

class _InlineExecutor(BaseExecutor):
    """Runs jobs synchronously in the APScheduler thread — no thread pool needed."""

    def start(self, scheduler, alias):
        super().start(scheduler, alias)

    def shutdown(self, wait=True):
        pass

    def _do_submit_job(self, job, run_times):
        try:
            self._run_job_success(job.id, [job.func(*job.args, **job.kwargs)])
        except Exception as exc:
            self._run_job_error(job.id, exc)


def start_scheduler() -> None:
    """Start the background scheduler (idempotent — safe to call more than once)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    executors = {"default": _InlineExecutor()}
    _scheduler = BackgroundScheduler(daemon=True, executors=executors)
    _scheduler.add_job(_tick, "interval", minutes=1, id="pull_tick", replace_existing=True)
    _scheduler.add_job(
        unified_inventory_import_job,
        "interval",
        minutes=5,
        id="unified_inventory_import_tick",
        replace_existing=True,
    )
    _scheduler.add_job(
        discrepancy_engine_job,
        "interval",
        minutes=6,
        id="discrepancy_engine_tick",
        replace_existing=True,
    )
    _scheduler.add_job(
        run_cleanup_job,
        "interval",
        hours=12,
        id="cleanup_tick",
        replace_existing=True,
    )
    _scheduler.start()
    log.info(
        "Background scheduler started — pull tick 1m, unified import 5m, discrepancy 6m, cleanup 12h, %d functions registered",
        len(_DISPATCH),
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Background scheduler stopped")


def get_supported_functions() -> list[str]:
    """Return the list of function names this scheduler can execute."""
    return sorted(_DISPATCH.keys())