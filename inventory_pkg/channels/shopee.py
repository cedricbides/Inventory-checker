"""
Shopee channel reader.

Public API
----------
read_shopee_file(file_path)  -> (channel, brand, sku_data, warnings, cols, channel_label)
scan_shopee_columns(paths)   -> list[str]
"""
import io
import os
import zipfile
import xml.etree.ElementTree as ET

from ..utils import (
    get_shared_strings,
    xml_cell_val,
    scan_xlsx_bytes_headers,
    is_valid_sku,
    detect_brand_from_name,
)

def _parse_shopee_all(content, sku_data, detected_brands):
    """
    Parse a Shopee xlsx blob. Populates sku_data (keyed by SKU) and detected_brands.
    Returns the ordered column list.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as inner:
        strings = get_shared_strings(inner)
        with inner.open("xl/worksheets/sheet1.xml") as ws:
            root = ET.parse(ws).getroot()

    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    col_map = {}
    headers = []
    header_found = False

    for row in root.findall(".//x:row", ns):
        cells = {}
        for c in row.findall("x:c", ns):
            ref = c.get("r", "")
            letter = "".join(filter(str.isalpha, ref))
            cells[letter] = xml_cell_val(c, strings, ns)

        if not header_found:
            if "Product ID" in cells.values():
                col_map = {lt: val for lt, val in cells.items() if val}
                headers = [val for _, val in sorted(col_map.items()) if val]
                header_found = True
            continue

        row_dict = {col_name: cells.get(lt, "") for lt, col_name in col_map.items()}
        sku = row_dict.get("SKU", "").strip()
        product_id = row_dict.get("Product ID", "").strip()
        if not sku or not product_id or not is_valid_sku(sku):
            continue

        product_name = row_dict.get("Product Name", "").strip()
        brand = detect_brand_from_name(product_name) if product_name else None
        if brand:
            detected_brands[brand] = detected_brands.get(brand, 0) + 1

        row_dict["_brand"] = brand
        sku_data[sku] = row_dict

    return headers

def scan_shopee_columns(file_paths):
    """Return a deduplicated ordered header list across all Shopee files."""
    cols, seen = [], set()
    for file_path in file_paths:
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".zip":
                with zipfile.ZipFile(file_path) as outer:
                    xlsx_names = sorted(n for n in outer.namelist() if n.endswith(".xlsx"))
                    hdrs = []
                    if xlsx_names:
                        with outer.open(xlsx_names[0]) as f:
                            hdrs = scan_xlsx_bytes_headers(f.read())
            elif ext in (".xlsx", ".xls"):
                with open(file_path, "rb") as f:
                    hdrs = scan_xlsx_bytes_headers(f.read())
            else:
                hdrs = []

            for h in hdrs:
                if h and h not in seen:
                    seen.add(h)
                    cols.append(h)
        except Exception as e:
            print(f"    shopee scan error {file_path}: {e}")
    return cols

def read_shopee_file(file_path):
    """
    Read a Shopee inventory file (ZIP or XLSX).

    Returns (channel, brand, sku_data, warnings, cols, channel_label).
    """
    channel = "Shopee"
    channel_label = "Channel_Shopee"
    sku_data, detected_brands, warnings = {}, {}, []
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".zip":
        blobs = []
        with zipfile.ZipFile(file_path) as outer:
            for n in sorted(n for n in outer.namelist() if n.endswith(".xlsx")):
                with outer.open(n) as f:
                    blobs.append(f.read())
    elif ext in (".xlsx", ".xls"):
        with open(file_path, "rb") as f:
            blobs = [f.read()]
    else:
        warnings.append(f"Unsupported file type: {ext}")
        return channel, "Unknown", {}, warnings, [], channel_label

    all_cols = []
    for blob in blobs:
        cols = _parse_shopee_all(blob, sku_data, detected_brands)
        if not all_cols:
            all_cols = cols

    dominant_brand = (
        max(detected_brands, key=detected_brands.get) if detected_brands else "Unknown"
    )
    if not detected_brands:
        warnings.append(f"Could not detect brand from product names in {os.path.basename(file_path)}")

    print(f"    channel=Shopee  brand={dominant_brand}  rows={len(sku_data)}")
    for w in warnings:
        print(f"    WARNING: {w}")
    return channel, dominant_brand, sku_data, warnings, all_cols, channel_label
