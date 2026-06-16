"""
Zalora channel reader.

Supports Zalora SellerStockTemplate format (SellerSku, Quantity columns).

Public API
----------
read_zalora_file(file_path, brand_override=None, extract_mpid=False, extract_mpskuid=False)
    -> (channel, brand, sku_data, warnings, cols, channel_label)
scan_zalora_columns(file_paths) -> list[str]
"""
import io
import os
import zipfile
import xml.etree.ElementTree as ET

from ..utils import (
    _NS,
    _build_cells,
    append_unique_values,
    detect_brand_from_filename,
    detect_brand_from_file,
    get_shared_strings,
    xml_cell_val,
    scan_xlsx_bytes_headers_generic,
)
from ..zalora_api import fetch_zalora_mpid_map, ZALORA_CREDENTIALS, COL_MPSKU_ID, COL_MPITEM_ID

_SELLER_SKU_ALIASES = {"sellersku", "seller sku", "seller_sku", "sku"}


def _parse_zalora_template(content, sku_data):
    """
    Parse a Zalora xlsx blob generically.
    First non-empty row = headers. SellerSku column = row key.
    Returns the ordered column list.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as inner:
            strings = get_shared_strings(inner)
            sheet_names = sorted(
                n for n in inner.namelist()
                if n.startswith("xl/worksheets/sheet")
            )
            for sheet_path in sheet_names:
                with inner.open(sheet_path) as ws:
                    root = ET.parse(ws).getroot()

                col_map = {}
                headers = []
                header_found = False
                sku_col = None

                for row in root.findall(".//x:row", _NS):
                    cells = _build_cells(row, strings, _NS)

                    if not any(v for v in cells.values() if v):
                        continue

                    if not header_found:
                        col_map = {lt: val for lt, val in cells.items() if val}
                        headers = [val for _, val in sorted(col_map.items()) if val]
                        header_found = True
                        for lt, hdr in col_map.items():
                            if hdr.strip().lower() in _SELLER_SKU_ALIASES:
                                sku_col = lt
                                break
                        continue

                    row_dict = {col_name: cells.get(lt, "").strip()
                                for lt, col_name in col_map.items()}

                    sku = cells.get(sku_col, "").strip() if sku_col else ""
                    if not sku:
                        for hdr, val in row_dict.items():
                            if hdr.strip().lower() in _SELLER_SKU_ALIASES and val:
                                sku = val
                                break
                    if not sku:
                        continue

                    sku_data[sku] = row_dict

                if headers:
                    return headers

    except Exception as e:
        print(f"    zalora parse error: {e}")
    return []


def _parse_blobs(blobs, sku_data):
    """
    Parse a list of xlsx blobs into sku_data.
    Returns the column list from the first blob that has one.
    """
    all_cols = []
    for blob in blobs:
        cols = _parse_zalora_template(blob, sku_data)
        if not all_cols:
            all_cols = cols
    return all_cols


def scan_zalora_columns(file_paths):
    """
    Return deduplicated headers from all Zalora files.
    Only columns present in the actual file headers are returned.
    """
    cols, seen = [], set()
    for file_path in file_paths:
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".zip":
                with zipfile.ZipFile(file_path) as outer:
                    xlsx_names = sorted(n for n in outer.namelist() if n.endswith(".xlsx"))
                    if xlsx_names:
                        with outer.open(xlsx_names[0]) as f:
                            hdrs = scan_xlsx_bytes_headers_generic(f.read())
            elif ext in (".xlsx", ".xls"):
                with open(file_path, "rb") as f:
                    hdrs = scan_xlsx_bytes_headers_generic(f.read())
            elif ext == ".csv":
                import csv as _csv
                with open(file_path, newline="", encoding="utf-8-sig") as f:
                    hdrs = next(_csv.reader(f), [])
            else:
                hdrs = []
            append_unique_values(cols, seen, hdrs)
        except Exception as e:
            print(f"    zalora scan error {file_path}: {e}")

    return cols


def read_zalora_file(file_path, brand_override=None, extract_mpid=False, extract_mpskuid=False):
    """
    Read a Zalora SellerStockTemplate file and optionally fetch MPID from API.

    Returns (channel, brand, sku_data, warnings, cols, channel_label).
    """
    channel = "Zalora"
    channel_label = "Channel_Zalora"
    sku_data, warnings = {}, []
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".zip":
        with zipfile.ZipFile(file_path) as outer:
            blobs = [
                outer.open(n).read()
                for n in sorted(n for n in outer.namelist() if n.endswith(".xlsx"))
            ]
        all_cols = _parse_blobs(blobs, sku_data)

    elif ext in (".xlsx", ".xls"):
        with open(file_path, "rb") as f:
            blobs = [f.read()]
        all_cols = _parse_blobs(blobs, sku_data)

    elif ext == ".csv":
        import csv as _csv
        all_cols = []
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            all_cols = list(reader.fieldnames or [])
            for row in reader:
                row = {k: (v or "").strip() for k, v in row.items()}
                sku = ""
                for alias in _SELLER_SKU_ALIASES:
                    for k in row:
                        if k.strip().lower() == alias and row[k]:
                            sku = row[k]
                            break
                    if sku:
                        break
                if sku:
                    sku_data[sku] = row
    else:
        warnings.append(f"Unsupported file type: {ext}")
        return channel, "Unknown", {}, warnings, [], channel_label

    print(f"    Zalora parsed {len(sku_data)} SKUs from {os.path.basename(file_path)}")

    dominant_brand = brand_override or (
        detect_brand_from_filename(file_path)
        or detect_brand_from_file(file_path)
        or "Unknown"
    )
    if dominant_brand == "Unknown":
        warnings.append(f"Could not detect brand from {os.path.basename(file_path)} — select brand in GUI")

    for row in sku_data.values():
        row.setdefault(COL_MPSKU_ID, "")
        row.setdefault(COL_MPITEM_ID, "")

    if (extract_mpid or extract_mpskuid) and sku_data:
        if dominant_brand in ZALORA_CREDENTIALS:
            try:
                mpid_map = fetch_zalora_mpid_map(list(sku_data.keys()), dominant_brand)
                for sku, row in sku_data.items():
                    ids = mpid_map.get(str(sku), {})
                    if extract_mpskuid:
                        row[COL_MPSKU_ID] = ids.get(COL_MPSKU_ID, "")
                    if extract_mpid:
                        row[COL_MPITEM_ID] = ids.get(COL_MPITEM_ID, "")
            except Exception as e:
                msg = f"Zalora API error: {e}"
                warnings.append(msg)
                print(f"    WARNING: {msg}")
        else:
            msg = (f"No Zalora API credentials for '{dominant_brand}'. "
                   f"MPID columns will be empty.")
            warnings.append(msg)
            print(f"    WARNING: {msg}")

    print(f"    channel=Zalora  brand={dominant_brand}  rows={len(sku_data)}")
    for w in warnings:
        print(f"    WARNING: {w}")
    return channel, dominant_brand, sku_data, warnings, all_cols, channel_label