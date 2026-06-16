"""
Lazada channel reader.

Public API
----------
read_lazada_file(file_path)   -> (channel, brand, sku_data, warnings, cols, channel_label)
scan_lazada_columns(paths)    -> list[str]
"""
import os
import zipfile
import xml.etree.ElementTree as ET

from ..utils import (
    _NS,
    _build_cells,
    _sorted_vals,
    append_unique_values,
    get_shared_strings,
    xml_cell_val,
    scan_xlsx_bytes_headers,
    is_valid_sku,
    detect_brand_from_filename,
    detect_brand_from_name,
)

_HEADER_COLS = {"Product ID", "sku.skuId", "SellerSKU"}


def _parse_lazada_all(file_path, sku_data, detected_brands):
    """
    Parse a Lazada xlsx export. Populates sku_data keyed by SellerSKU (falling back to
    Product ID). Lazada exports have 3 metadata rows after the real header — those are skipped.
    Returns the ordered column list.
    """
    try:
        with zipfile.ZipFile(file_path) as z:
            strings = get_shared_strings(z)
            with z.open("xl/worksheets/sheet1.xml") as ws:
                root = ET.parse(ws).getroot()

        col_map = {}
        headers = []
        header_found = False
        skip_rows = 0

        for row in root.findall(".//x:row", _NS):
            cells = _build_cells(row, strings, _NS)

            if not header_found:
                if _HEADER_COLS.issubset(set(cells.values())):
                    col_map = {lt: val for lt, val in cells.items() if val}
                    headers = [val for _, val in sorted(col_map.items()) if val]
                    header_found = True
                    skip_rows = 3
                continue

            if skip_rows > 0:
                skip_rows -= 1
                continue
            if not any(cells.values()):
                continue

            row_dict = {col_name: cells.get(lt, "") for lt, col_name in col_map.items()}
            sku = row_dict.get("SellerSKU", "").strip()
            product_id = row_dict.get("Product ID", "").strip()
            key = sku or product_id
            if not key or not is_valid_sku(key):
                continue
            product_name = row_dict.get("Product Name", "").strip()
            brand = detect_brand_from_name(product_name) if product_name else None
            if brand:
                detected_brands[brand] = detected_brands.get(brand, 0) + 1
            row_dict["_brand"] = brand
            sku_data[key] = row_dict

        return headers

    except Exception as e:
        print(f"    Lazada read error: {e}")
        return []


def scan_lazada_columns(file_paths):
    """Return a deduplicated ordered header list across all Lazada files."""
    cols, seen = [], set()
    for file_path in file_paths:
        try:
            with open(file_path, "rb") as f:
                hdrs = scan_xlsx_bytes_headers(f.read())
            append_unique_values(cols, seen, hdrs)
        except Exception as e:
            print(f"    lazada scan error {file_path}: {e}")
    return cols


def read_lazada_file(file_path):
    """
    Read a Lazada inventory file (XLSX).

    Returns (channel, brand, sku_data, warnings, cols, channel_label).
    """
    channel = "Lazada"
    channel_label = "Channel_Lazada"
    sku_data, detected_brands, warnings = {}, {}, []

    cols = _parse_lazada_all(file_path, sku_data, detected_brands)

    if detected_brands:
        brand = max(detected_brands, key=detected_brands.get)
    else:
        brand = detect_brand_from_filename(file_path) or "Unknown"
        if brand == "Unknown":
            warnings.append(
                f"Could not detect brand from Lazada filename "
                f"'{os.path.basename(file_path)}' or Product Name column."
            )

    print(f"    channel=Lazada  brand={brand}  rows={len(sku_data)}")
    for w in warnings:
        print(f"    WARNING: {w}")
    return channel, brand, sku_data, warnings, cols, channel_label