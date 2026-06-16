"""
Ordazzle inventory reader.

Public API
----------
read_ordazzle_file(path, warehouse_filter=None)  -> (data, headers)
read_ordazzle_files(paths, warehouse_filter=None) -> (merged_data, headers)
scan_ordazzle_columns(paths)                      -> list[str]
"""
import os
import zipfile
import xml.etree.ElementTree as ET

from ..utils import (
    _NS,
    _build_cells,
    append_unique_values,
    get_shared_strings,
    xml_cell_val,
    is_valid_sku,
    merge_row,
)


def _iter_sheets(z):
    """Yield (sheet_path, root) for all sheets in an xlsx ZipFile."""
    strings = get_shared_strings(z)
    for sheet_path in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
        with z.open(sheet_path) as ws:
            root = ET.parse(ws).getroot()
        yield strings, sheet_path, root


def scan_ordazzle_columns(ordazzle_paths):
    """Return a deduplicated ordered header list from Ordazzle files."""
    cols, seen = [], set()
    for path in ordazzle_paths:
        try:
            with zipfile.ZipFile(path) as z:
                for strings, _, root in _iter_sheets(z):
                    for row in root.findall(".//x:row", _NS):
                        cells_list = [v for _, v in sorted(_build_cells(row, strings, _NS).items())]
                        if "PRODUCT CODE" in cells_list:
                            append_unique_values(cols, seen, cells_list)
                            break
        except Exception as e:
            print(f"    ordazzle scan error {path}: {e}")
    return cols


def read_ordazzle_file(path, warehouse_filter=None):
    """
    Read all columns from one Ordazzle file.

    Supports both xlsx (ZipFile) and legacy .xls (via pandas/xlrd).
    Duplicate SKUs are merged by summing numeric fields.

    Returns (data, headers) where data is {product_code: {col: val}}.
    """
    data, headers = {}, []

    try:
        with zipfile.ZipFile(path) as z:
            for strings, sheet_path, root in _iter_sheets(z):
                hdr = None
                diag_nodes = set()
                diag_count = 0

                for row in root.findall(".//x:row", _NS):
                    cells = _build_cells(row, strings, _NS)
                    cells_list = [v for _, v in sorted(cells.items())]

                    if hdr is None:
                        if "PRODUCT CODE" in cells_list:
                            hdr = cells_list
                            headers = headers or [h for h in hdr if h]
                        continue
                    if not any(cells_list):
                        continue

                    row_dict = dict(zip(hdr, cells_list))
                    sku = str(row_dict.get("PRODUCT CODE", "")).strip()
                    node_name = str(row_dict.get("NODE NAME", "")).strip()
                    if not sku:
                        continue
                    if len(diag_nodes) < 5:
                        diag_nodes.add(repr(node_name))
                    diag_count += 1
                    if not is_valid_sku(sku):
                        continue
                    if warehouse_filter and node_name != warehouse_filter:
                        continue

                    if sku in data:
                        merge_row(data[sku], row_dict)
                    else:
                        data[sku] = dict(row_dict)

                if warehouse_filter:
                    if diag_count == 0:
                        print(f"    x Ordazzle: no data rows in {os.path.basename(path)}")
                    elif not data:
                        print(f"    x Ordazzle filter '{warehouse_filter}' matched 0 of "
                              f"{diag_count} rows.")
                        print(f"      NODE NAME values found: {', '.join(sorted(diag_nodes))}")
                        print(f"      > Check warehouse constant matches exactly.")
                    else:
                        print(f"    > Ordazzle filter '{warehouse_filter}' matched "
                              f"{len(data)} SKUs from {diag_count} rows.")

    except zipfile.BadZipFile:
        print(f"    Ordazzle: {os.path.basename(path)} is binary .xls — trying xlrd...")
        try:
            import pandas as pd
            df = pd.read_excel(path, engine="xlrd", dtype=str)
            df.columns = [str(c).strip() for c in df.columns]
            if "PRODUCT CODE" not in df.columns:
                print(f"    Ordazzle xls: 'PRODUCT CODE' not found.")
                return data, headers
            headers = list(df.columns)
            diag_nodes = set()
            for _, row in df.iterrows():
                sku = str(row.get("PRODUCT CODE", "")).strip()
                node_name = str(row.get("NODE NAME", "")).strip()
                if not sku or sku == "nan":
                    continue
                if len(diag_nodes) < 5:
                    diag_nodes.add(repr(node_name))
                if not is_valid_sku(sku):
                    continue
                if warehouse_filter and node_name != warehouse_filter:
                    continue
                row_dict = {k: ("" if str(v) == "nan" else str(v).strip())
                            for k, v in row.items()}
                if sku in data:
                    merge_row(data[sku], row_dict)
                else:
                    data[sku] = row_dict

            if warehouse_filter and not data:
                print(f"    Ordazzle xls filter '{warehouse_filter}' matched 0 rows.")
                print(f"      NODE NAME values: {', '.join(sorted(diag_nodes))}")
            elif data:
                print(f"    Ordazzle xls: {len(data)} SKUs loaded.")
        except Exception as xe:
            print(f"    Ordazzle xls read error: {xe}")

    except Exception as e:
        print(f"    Ordazzle read error: {e}")

    return data, headers


def read_ordazzle_files(paths, warehouse_filter=None):
    """Read and merge multiple Ordazzle files. Returns (merged_data, headers)."""
    merged, all_headers = {}, []
    for p in paths:
        print(f"    Ordazzle source: {os.path.basename(p)}")
        data, hdrs = read_ordazzle_file(p, warehouse_filter=warehouse_filter)
        if not all_headers:
            all_headers = hdrs
        for sku, row in data.items():
            if sku in merged:
                merge_row(merged[sku], row)
            else:
                merged[sku] = dict(row)
    return merged, all_headers