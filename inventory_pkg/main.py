"""
Inventory Checker  main entry point.

Drop all source files in the same folder as this script, then run:
    python -m inventory_pkg

File naming conventions
-----------------------
  MASS*.zip / MASS*.xlsx       Shopee channel
  price*.xlsx / lazada*.xlsx   Lazada channel
  zalora*.xlsx / zalora*.zip   Zalora channel
  EXL*.xls / EXP*.xls/.xlsx    Ordazzle
  Article*.xlsx                SAP
  Modify*.xlsx  (or any xlsx whose docProps shows a real user)  user-modified
"""
import os
from datetime import datetime

from .config import FOLDERS, OUTPUT
from .constants import (
    PAYLESS_WAREHOUSE, PAYLESS_SAP_SITE, PAYLESS_STORAGE_LOC,
    SLCI_WAREHOUSE,   SLCI_SAP_SITE,   SLCI_STORAGE_LOC,
    SSIEBG_WAREHOUSE, SSIEBG_SAP_SITE, SSIEBG_STORAGE_LOC,
)
from .utils import brand_group, safe_filename, detect_channel_from_filename
from .file_finder import find_files
from .channels import (
    read_channel_file,
    scan_channel_columns,
    scan_channel_columns_per_file,
)
from .readers import (
    read_ordazzle_files, scan_ordazzle_columns,
    read_sap_files,      scan_sap_columns,
    read_modify_files,   scan_modify_columns, scan_modify_columns_per_file,
)
from .output  import build_output
from .gui     import launch_gui

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.dirname(SCRIPT_DIR)   # parent folder (where files are dropped)

def setup_folders():
    """Create all required working folders if they don't exist yet."""
    created = []
    for folder in FOLDERS.values():
        path = os.path.join(WORKING_DIR, folder)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            created.append(folder)
    if created:
        print(f"\n  First-time setup: created folders → {', '.join(created)}")
        print(f"  Drop your files in the correct folder and re-run.\n")

# Override auto-detection by setting these to explicit file lists, e.g.:
#   CHANNEL_FILES  = [r"C:\data\MASS_Lacoste.zip"]
CHANNEL_FILES  = None
ORDAZZLE_FILES = None
SAP_FILES      = None

def run():
    print("\nINVENTORY CHECKER")
    setup_folders()

    if any(x is None for x in (CHANNEL_FILES, ORDAZZLE_FILES, SAP_FILES)):
        auto_ch, auto_ord, auto_sap, _mod, _modify_source, _modify_files = find_files()
        channel_files     = CHANNEL_FILES  or auto_ch
        ordazzle_files    = ORDAZZLE_FILES or auto_ord
        sap_files         = SAP_FILES      or auto_sap
    else:
        channel_files     = CHANNEL_FILES
        ordazzle_files    = ORDAZZLE_FILES
        sap_files         = SAP_FILES

    # Modify feature disabled — force empty
    modify_files_list = []
    modify_source     = None
    modify_files      = []

    print(f"\nFiles found:")
    print(f"  Channel  : {[os.path.basename(z) for z in channel_files]}")
    print(f"  Ordazzle : {[os.path.basename(f) for f in ordazzle_files] or 'NOT FOUND'}")
    print(f"  SAP      : {[os.path.basename(f) for f in sap_files] or 'NOT FOUND'}")

    if not channel_files:
        print("\nWARNING: No channel files (MASS*/price*/zalora*) found — channel columns will be empty.")
    if not ordazzle_files:
        print("\nWARNING: No Ordazzle (EXL*/EXP*) file found — Ordazzle columns will be empty.")
    if not sap_files:
        print("\nWARNING: No SAP (Article*.xlsx) file found — SAP columns will be empty.")

    print("\nScanning columns from source files...")
    channel_sources = scan_channel_columns_per_file(channel_files)
    channel_cols    = scan_channel_columns(channel_files)
    ordazzle_cols   = scan_ordazzle_columns(ordazzle_files)
    sap_cols        = scan_sap_columns(sap_files)
    modify_cols          = []
    modify_cols_per_file = {}

    for sk, dl, cols in channel_sources:
        print(f"  {dl} cols ({len(cols)}): {cols[:8]}{'…' if len(cols) > 8 else ''}")
    print(f"  Ordazzle cols ({len(ordazzle_cols)}): {ordazzle_cols[:8]}{'…' if len(ordazzle_cols) > 8 else ''}")
    print(f"  SAP      cols ({len(sap_cols)}):      {sap_cols[:8]}{'…' if len(sap_cols) > 8 else ''}")
    from .utils import detect_brand_from_filename, detect_brand_from_file, detect_channel_from_filename
    file_brand_map = {}   # file_path -> (brand_label, channel_label)
    for fp in channel_files:
        b = detect_brand_from_filename(fp) or detect_brand_from_file(fp) or "Unknown"
        c = detect_channel_from_filename(fp) or "Channel"
        ch_short = c.replace("Channel_", "")
        file_brand_map[fp] = (b, ch_short)
        print(f"  Detected brand: {b} — {ch_short}  ({os.path.basename(fp)})")

    selected_output_cols, comparisons, base_sku, selected_files, zalora_options = launch_gui(
        channel_files, ordazzle_files, sap_files,
        channel_cols, ordazzle_cols, sap_cols,
        suggested_base=modify_source,
        modify_files=modify_files,
        modify_files_list=modify_files_list,
        modify_cols=modify_cols,
        modify_cols_per_file=modify_cols_per_file,
        channel_sources=channel_sources,
        file_brand_map=file_brand_map,
    )
    if selected_output_cols is None:
        print("Cancelled.")
        return

    # Apply brand filter — only process files the user ticked
    if selected_files is not None:
        channel_files = [f for f in channel_files if f in selected_files]
        print(f"\nBrand filter applied — processing {len(channel_files)} file(s):"
              f" {[os.path.basename(f) for f in channel_files]}")

    timestamp       = datetime.now().strftime(OUTPUT.get("timestamp_format", "%Y-%m-%d_%H-%M"))
    results_summary = []

    for file_path in channel_files:
        # Determine this file's source key (channel_shopee / channel_lazada / channel_zalora)
        _CH_SRC_KEY = {
            "Channel_Shopee": "channel_shopee",
            "Channel_Lazada": "channel_lazada",
            "Channel_Zalora": "channel_zalora",
        }
        _file_ch_label = detect_channel_from_filename(file_path) or "Channel_Shopee"
        _file_src_key  = _CH_SRC_KEY.get(_file_ch_label, "channel_shopee")

        # Skip if the user left this marketplace completely unchecked
        _has_cols = any(src == _file_src_key for src, _ in selected_output_cols)
        if not _has_cols:
            print(f"\nSkipping {os.path.basename(file_path)} — no columns selected for {_file_ch_label}.")
            continue

        print(f"\nProcessing: {os.path.basename(file_path)}")

        channel, brand, channel_data, file_warnings, _, channel_label = read_channel_file(
            file_path,
            **(
                {
                    "extract_mpid":    (zalora_options or {}).get("extract_mpid",    False),
                    "extract_mpskuid": (zalora_options or {}).get("extract_mpskuid", False),
                    "brand_override":  (zalora_options or {}).get("zalora_file_brands", {}).get(file_path),
                }
                if _file_ch_label == "Channel_Zalora" else {}
            )
        )
        group      = brand_group(brand)
        brand_safe = safe_filename(brand)
        ordazzle_warning = None

        if group == "PAYLESS":
            print(f"  Reading Ordazzle (filter: {PAYLESS_WAREHOUSE})")
            ordazzle_data, _ = read_ordazzle_files(ordazzle_files, warehouse_filter=PAYLESS_WAREHOUSE)
            print(f"    {len(ordazzle_data)} SKUs")
            print(f"  Reading SAP (site: {PAYLESS_SAP_SITE}, loc: {PAYLESS_STORAGE_LOC})")
            sap_data, _ = read_sap_files(sap_files,
                                         site_filter=PAYLESS_SAP_SITE,
                                         storage_loc_filter=PAYLESS_STORAGE_LOC)
            print(f"    {len(sap_data)} articles")

        elif group == "SLCI":
            print(f"  Reading Ordazzle (filter: {SLCI_WAREHOUSE})")
            ordazzle_data, _ = read_ordazzle_files(ordazzle_files, warehouse_filter=SLCI_WAREHOUSE)
            print(f"    {len(ordazzle_data)} SKUs")
            print(f"  Reading SAP (site: {SLCI_SAP_SITE}, loc: {SLCI_STORAGE_LOC})")
            sap_data, _ = read_sap_files(sap_files,
                                         site_filter=SLCI_SAP_SITE,
                                         storage_loc_filter=SLCI_STORAGE_LOC)
            print(f"    {len(sap_data)} articles")

        elif group == "SSIEBG":
            print(f"  Reading Ordazzle (filter: {SSIEBG_WAREHOUSE})")
            ordazzle_data, _ = read_ordazzle_files(ordazzle_files, warehouse_filter=SSIEBG_WAREHOUSE)
            print(f"    {len(ordazzle_data)} SKUs")
            print(f"  Reading SAP (site: {SSIEBG_SAP_SITE}, loc: {SSIEBG_STORAGE_LOC})")
            sap_data, _ = read_sap_files(sap_files,
                                         site_filter=SSIEBG_SAP_SITE,
                                         storage_loc_filter=SSIEBG_STORAGE_LOC)
            print(f"    {len(sap_data)} articles")

        else:
            ordazzle_warning = (
                f"UNKNOWN BRAND '{brand}': reading all Ordazzle & SAP rows without filtering."
            )
            print(f"\n  UNKNOWN BRAND '{brand}' — no warehouse/site filter applied.")
            ordazzle_data, _ = read_ordazzle_files(ordazzle_files)
            sap_data, _      = read_sap_files(sap_files)

        modify_data = {}

        print(f"  Building output...")

        # Resolve per-marketplace base SKU (base_sku may be a dict when
        # multiple channel files with different marketplace types are present)
        if isinstance(base_sku, dict):
            effective_base = base_sku.get(_file_src_key, _file_src_key)
        else:
            effective_base = base_sku

        wb, total_skus, matched_ord, matched_sap = build_output(
            brand, channel_data, ordazzle_data, sap_data,
            channel=channel,
            channel_label=channel_label,
            ordazzle_warning=ordazzle_warning,
            base_sku=effective_base,
            selected_output_cols=selected_output_cols,
            comparisons=comparisons,
            modify_data=modify_data,
        )

        _prefix    = OUTPUT.get("file_prefix", "Inventory_Result_")
        out_name   = f"{_prefix}{brand_safe}_{channel}_{timestamp}.xlsx"
        result_dir = os.path.join(WORKING_DIR, FOLDERS.get("result", "RESULT"))
        os.makedirs(result_dir, exist_ok=True)
        wb.save(os.path.join(result_dir, out_name))

        results_summary.append({
            "brand": brand, "channel": channel, "group": group, "file": out_name,
            "channel_files":  [os.path.basename(file_path)],
            "ordazzle_files": [os.path.basename(f) for f in ordazzle_files],
            "sap_files":      [os.path.basename(f) for f in sap_files],
            "total_skus": total_skus, "matched_ord": matched_ord, "matched_sap": matched_sap,
            "warnings": file_warnings + ([ordazzle_warning] if ordazzle_warning else []),
        })  
        print(f"  Saved: RESULT/{out_name}")

    print("\nSUMMARY")
    for r in results_summary:
        print(f"\n  Brand      : {r['brand']} ({r['group']}) — {r['channel'].upper()}")
        print(f"  File       : {r['file']}")
        print(f"  Files used : CH={r['channel_files']} | ORD={r['ordazzle_files']} | SAP={r['sap_files']}")
        print(f"  Rows       : {r['total_skus']} total | "
              f"{r['matched_ord']} matched Ordazzle | {r['matched_sap']} matched SAP")
        for w in r["warnings"]:
            print(f"  WARNING: {w}")

if __name__ == "__main__":
    run()