"""
routes/check_routes.py — inventory comparison endpoints.

  POST /api/check/upload   accept files, detect types, return job_id + summary
  POST /api/check/scan     return available columns per source
  POST /api/check/run      run the comparison, return download URL
  GET  /api/check/download/<job_id>/<token>

Side effect of /api/check/run:
  After read_ordazzle_files() succeeds, the parsed data is saved to the
  ordazzle_snapshot table in SQLite. The discrepancy engine reads from
  there instead of calling a (non-existent) Ordazzle API.
"""

import io
import json
import logging
import os
import uuid
import zipfile
from datetime import datetime
from routes.auth_routes import login_required

from flask import Blueprint, jsonify, request, send_file

from helpers import (
    load_settings,
    warehouse_for_brand,
    job_dir, save_state, load_state, save_upload,
    is_download_token_valid, load_download_info,
)
from inventory_pkg.channels import (
    read_channel_file,
    scan_channel_columns_per_file,
    read_shopee_file,
    read_lazada_file,
    read_zalora_file,
)
from inventory_pkg.output import build_output
from inventory_pkg.readers import (
    read_ordazzle_files,
    read_sap_files,
    scan_ordazzle_columns,
    scan_sap_columns,
)
from inventory_pkg.run_history import append_run
from inventory_pkg.utils import (
    brand_group,
    detect_brand_from_file,
    detect_brand_from_filename,
    detect_channel_from_filename,
    detect_file_type_flexible,
    safe_filename,
)

log = logging.getLogger(__name__)

check_bp = Blueprint("check", __name__)

_CHANNEL_TYPES = {"Channel_Shopee", "Channel_Lazada", "Channel_Zalora"}
_ORDAZZLE_TYPE = "ordazzle"
_SAP_TYPE      = "sap"
_CH_SRC_KEY    = {
    "Channel_Shopee": "channel_shopee",
    "Channel_Lazada": "channel_lazada",
    "Channel_Zalora": "channel_zalora",
}
_CHANNEL_READERS = {
    "Shopee": read_shopee_file,
    "Lazada": read_lazada_file,
    "Zalora": read_zalora_file,
}

# Ordazzle column names that represent published/available stock
_ORD_STOCK_KEYS = (
    "INV TO PUBLISHED STOCK",
    "PUBLISHED STOCK",
    "Inventory published",
    "UNRESTRICTED STOCK",
)


# ── Ordazzle snapshot helper ───────────────────────────────────────────────────

def _save_ordazzle_snapshot(ordazzle_data: dict, node_name: str, brand: str) -> None:
    """
    Persist the Ordazzle upload to ordazzle_snapshot so the discrepancy
    engine can compare marketplace stock against it without a live API.

    Replaces the previous snapshot for this warehouse node entirely —
    one upload per warehouse is kept (the latest).

    Never raises — snapshot failure must never block the report download.
    """
    if not ordazzle_data:
        return
    try:
        from database import get_db
        upload_id = str(uuid.uuid4())
        now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rows = []
        for sku, row in ordazzle_data.items():
            stock = 0
            for k in _ORD_STOCK_KEYS:
                v = row.get(k)
                if v not in (None, ""):
                    try:
                        stock = int(float(v))
                        break
                    except (TypeError, ValueError):
                        pass
            rows.append((upload_id, sku, node_name, brand, stock, now))

        with get_db() as conn:
            conn.execute(
                "DELETE FROM ordazzle_snapshot WHERE node_name = ?",
                (node_name,),
            )
            conn.executemany(
                """
                INSERT INTO ordazzle_snapshot
                    (upload_id, sku, node_name, brand, inv_stock, uploaded_at)
                VALUES (?,?,?,?,?,?)
                """,
                rows,
            )
            conn.commit()

        log.info(
            "ordazzle_snapshot: saved %d SKUs for warehouse '%s' (brand=%s)",
            len(rows), node_name, brand,
        )
    except Exception as exc:
        log.warning("ordazzle_snapshot save failed (non-critical): %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
#  Upload
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@check_bp.route("/api/check/upload", methods=["POST"])
def api_check_upload():
    """
    Accept uploaded files, detect types, return job_id and file summary.
    The frontend shows this summary before the user clicks Run.
    """
    job_id = str(uuid.uuid4())
    os.makedirs(job_dir(job_id), exist_ok=True)

    channel_files:  list[str] = []
    ordazzle_files: list[str] = []
    sap_files:      list[str] = []

    for key, bucket in [
        ("channel_files",  channel_files),
        ("ordazzle_files", ordazzle_files),
        ("sap_files",      sap_files),
    ]:
        for f in request.files.getlist(key):
            if f and f.filename:
                bucket.append(save_upload(job_id, f, f.filename))

    if not channel_files and not ordazzle_files and not sap_files:
        return jsonify({"error": "Please upload at least one file."}), 400

    def _partition_files_by_detected_type(files, expected_types):
        accepted_files, to_ordazzle, to_sap, to_channel = [], [], [], []
        for fp in files:
            ft, _ = detect_file_type_flexible(fp)
            if ft in expected_types or ft is None:
                accepted_files.append(fp)
            elif ft == _ORDAZZLE_TYPE:
                to_ordazzle.append(fp)
            elif ft == _SAP_TYPE:
                to_sap.append(fp)
            elif ft in _CHANNEL_TYPES:
                to_channel.append(fp)
            else:
                accepted_files.append(fp)
        return accepted_files, to_ordazzle, to_sap, to_channel

    ch_ok, ch_ord, ch_sap, _ = _partition_files_by_detected_type(channel_files, _CHANNEL_TYPES)
    channel_files   = ch_ok
    ordazzle_files += ch_ord
    sap_files      += ch_sap

    ord_ok, _, ord_sap, ord_ch = _partition_files_by_detected_type(ordazzle_files, {_ORDAZZLE_TYPE})
    ordazzle_files  = ord_ok
    channel_files  += ord_ch
    sap_files      += ord_sap

    file_summary   = []
    file_brand_map = {}

    for fp in channel_files:
        brand = detect_brand_from_filename(fp) or detect_brand_from_file(fp) or "Unknown"
        ch    = detect_channel_from_filename(fp) or "Channel_Shopee"
        file_brand_map[fp] = {"brand": brand, "channel": ch}
        file_summary.append({
            "path":    fp,
            "name":    os.path.basename(fp),
            "type":    "channel",
            "brand":   brand,
            "channel": ch.replace("Channel_", ""),
        })
    for fp in ordazzle_files:
        file_summary.append({
            "path": fp, "name": os.path.basename(fp),
            "type": "ordazzle", "brand": "", "channel": "Ordazzle",
        })
    for fp in sap_files:
        file_summary.append({
            "path": fp, "name": os.path.basename(fp),
            "type": "sap", "brand": "", "channel": "SAP",
        })

    save_state(job_id, {
        "channel_files":  channel_files,
        "ordazzle_files": ordazzle_files,
        "sap_files":      sap_files,
        "file_brand_map": file_brand_map,
    })
    return jsonify({"job_id": job_id, "files": file_summary})


# ══════════════════════════════════════════════════════════════════════════════
#  Scan columns
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@check_bp.route("/api/check/scan", methods=["POST"])
def api_check_scan():
    """
    Scan uploaded files and return available columns per source.
    Called after upload, before run, so the frontend can show a column picker.
    """
    data   = request.get_json(force=True)
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "Missing job_id"}), 400

    try:
        state = load_state(job_id)
    except Exception:
        return jsonify({"error": "Job not found or expired."}), 404

    channel_files  = state["channel_files"]
    ordazzle_files = state["ordazzle_files"]
    sap_files      = state["sap_files"]

    sources = []

    if channel_files:
        try:
            channel_cols = scan_channel_columns_per_file(channel_files)
            for src_key, disp_label, cols in channel_cols:
                if cols:
                    sources.append({"source": src_key, "label": disp_label, "columns": cols})
        except Exception as e:
            log.warning("Channel column scan failed: %s", e)

    if ordazzle_files:
        try:
            ord_cols = scan_ordazzle_columns(ordazzle_files)
            if ord_cols:
                sources.append({"source": "ordazzle", "label": "Ordazzle", "columns": ord_cols})
        except Exception as e:
            log.warning("Ordazzle column scan failed: %s", e)

    if sap_files:
        try:
            sap_cols = scan_sap_columns(sap_files)
            if sap_cols:
                sources.append({"source": "sap", "label": "SAP", "columns": sap_cols})
        except Exception as e:
            log.warning("SAP column scan failed: %s", e)

    return jsonify({"sources": sources})


# ══════════════════════════════════════════════════════════════════════════════
#  Run
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@check_bp.route("/api/check/run", methods=["POST"])
def api_check_run():
    """
    Run the inventory comparison. Returns a download token for the result.

    Side effect: if Ordazzle files are included, the parsed data is saved
    to ordazzle_snapshot (per warehouse) so the discrepancy engine has
    something to compare against without needing a live Ordazzle API.
    """
    data   = request.get_json(force=True)
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "Missing job_id"}), 400

    try:
        state = load_state(job_id)
    except Exception:
        return jsonify({"error": "Job not found or expired. Please re-upload files."}), 404

    channel_files  = state["channel_files"]
    ordazzle_files = state["ordazzle_files"]
    sap_files      = state["sap_files"]

    selected = data.get("selected_files")
    if selected:
        channel_files = [f for f in channel_files if f in selected]

    file_overrides: dict[str, dict] = {
        item["path"]: item
        for item in data.get("file_overrides", [])
        if item.get("path")
    }

    base_sku   = data.get("base_sku", "channel")
    settings   = load_settings()
    warehouses = settings.get("warehouses", [])
    threshold  = settings.get("mismatch_threshold_pct", 10)
    timestamp  = datetime.now().strftime("%Y-%m-%d_%H-%M")
    result_files: list[tuple[str, io.BytesIO]] = []
    errors:       list[str] = []

    for file_path in channel_files:
        override         = file_overrides.get(file_path, {})
        override_channel = override.get("channel", "")
        override_brand   = override.get("brand", "")

        if override_channel and override_channel in _CHANNEL_READERS:
            reader_fn     = _CHANNEL_READERS[override_channel]
            file_ch_label = f"Channel_{override_channel}"
        else:
            file_ch_label = detect_channel_from_filename(file_path) or "Channel_Shopee"
            reader_fn     = _CHANNEL_READERS.get(
                file_ch_label.replace("Channel_", ""), read_shopee_file
            )

        try:
            channel, brand, channel_data, file_warnings, _, channel_label = reader_fn(file_path)
        except Exception as e:
            errors.append(f"{os.path.basename(file_path)}: {e}")
            continue

        if override_brand:
            brand = override_brand

        wh = warehouse_for_brand(brand, warehouses)
        if not wh:
            errors.append(
                f"Brand '{brand}' is not assigned to any warehouse. "
                f"Go to Warehouses → add this brand to a warehouse."
            )
            continue

        ordazzle_data, _ = read_ordazzle_files(ordazzle_files, warehouse_filter=wh["code"])
        sap_data,      _ = read_sap_files(
            sap_files,
            site_filter=wh.get("sap_site", ""),
            storage_loc_filter=wh.get("storage_loc", "0002"),
        )

        # ── Persist Ordazzle data for discrepancy engine ──────────────────────
        if ordazzle_data:
            _save_ordazzle_snapshot(ordazzle_data, wh["code"], brand)

        raw_cols = data.get("selected_output_cols", [])
        selected_output_cols = [
            (item["source"], item["col"])
            for item in raw_cols
            if item.get("source") and item.get("col")
        ]

        try:
            wb, total_skus, matched_ord, matched_sap = build_output(
                brand, channel_data, ordazzle_data, sap_data,
                channel=channel,
                channel_label=channel_label,
                ordazzle_warning=None,
                base_sku=base_sku,
                selected_output_cols=selected_output_cols,
                comparisons=[],
                modify_data={},
            )
        except Exception as e:
            errors.append(f"Build output for {brand}: {e}")
            continue

        if total_skus > 0:
            pct_ord = round((total_skus - matched_ord) / total_skus * 100, 1)
            if pct_ord > threshold:
                errors.append(
                    f"⚠ {brand} ({channel}): mismatch exceeds {threshold}% threshold — "
                    f"{pct_ord}% of SKUs unmatched in Ordazzle"
                )

        out_name = f"Inventory_Result_{safe_filename(brand)}_{channel}_{timestamp}.xlsx"
        buf      = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        result_files.append((out_name, buf))

        try:
            append_run(
                brand=brand,
                group=wh["name"],
                channel=channel,
                total_skus=total_skus,
                matched_ord=matched_ord,
                matched_sap=matched_sap,
                output_file=out_name,
            )
        except Exception:
            pass  # run history is non-critical

    if not result_files:
        msg = " | ".join(errors) if errors else "No files were processed."
        return jsonify({"error": msg}), 422

    dl_token = str(uuid.uuid4())
    dl_dir   = os.path.join(job_dir(job_id), "results")
    os.makedirs(dl_dir, exist_ok=True)

    if len(result_files) == 1:
        name, buf = result_files[0]
        out_path  = os.path.join(dl_dir, name)
        with open(out_path, "wb") as f:
            f.write(buf.read())
        with open(os.path.join(dl_dir, "download.json"), "w") as f:
            json.dump({"type": "xlsx", "filename": name, "path": out_path}, f)
    else:
        zip_name = f"Inventory_Results_{timestamp}.zip"
        zip_path = os.path.join(dl_dir, zip_name)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, buf in result_files:
                zf.writestr(name, buf.read())
        with open(os.path.join(dl_dir, "download.json"), "w") as f:
            json.dump({"type": "zip", "filename": zip_name, "path": zip_path}, f)

    with open(os.path.join(job_dir(job_id), "dl_token.txt"), "w") as f:
        f.write(dl_token)

    return jsonify({
        "ok":              True,
        "download_url":    f"/api/check/download/{job_id}/{dl_token}",
        "files_processed": len(result_files),
        "warnings":        errors,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  Download
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@check_bp.route("/api/check/download/<job_id>/<token>")
def api_check_download(job_id: str, token: str):
    token_ok = is_download_token_valid(job_id, token)
    if token_ok is None:
        return jsonify({"error": "Download expired"}), 404
    if not token_ok:
        return jsonify({"error": "Invalid token"}), 403

    dl_info = load_download_info(job_id)

    mime = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if dl_info["type"] == "xlsx"
        else "application/zip"
    )
    return send_file(
        dl_info["path"],
        as_attachment=True,
        download_name=dl_info["filename"],
        mimetype=mime,
    )