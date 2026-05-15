"""
utils.py

Shared helper functions used across the whole package.
Covers: raw xlsx parsing (no openpyxl dependency), SKU validation,
brand detection, and a few small formatters.
"""

import io
import os
import zipfile
import xml.etree.ElementTree as ET

from .constants import BRAND_KEYWORD_MAP, PAYLESS_BRANDS, SLCI_BRANDS, SSIEBG_BRANDS


def get_shared_strings(zf):
    """
    Pull the shared-strings table out of an open xlsx ZipFile.

    Excel stores repeated strings in a separate xl/sharedStrings.xml file
    and cells reference them by index. This reads that table into a list
    so xml_cell_val can resolve 't="s"' cells.

    Returns an empty list if the file has no shared strings (which is fine —
    it just means all values are inline).
    """
    try:
        with zf.open("xl/sharedStrings.xml") as ss:
            root = ET.parse(ss).getroot()
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            result = []
            for si in root.findall("x:si", ns):
                # A <si> element is either a plain <t> or a run of <r><t> fragments
                direct = si.findtext("x:t", namespaces=ns)
                if direct is not None:
                    result.append(direct)
                else:
                    parts = [
                        r.findtext("x:t", default="", namespaces=ns)
                        for r in si.findall("x:r", ns)
                    ]
                    result.append("".join(parts))
            return result
    except Exception:
        return []


def xml_cell_val(c, strings, ns):
    """
    Read the string value of a single <c> element from a worksheet XML.

    The cell type attribute 't' tells us how to interpret the value:
      's'         -> shared string index, look up in the strings table
      'inlineStr' -> the text is embedded directly in the cell
      (anything else) -> treat the <v> child as the raw value
    """
    t = c.get("t", "")
    if t == "s":
        idx = c.findtext("x:v", default="", namespaces=ns)
        return strings[int(idx)] if idx else ""
    if t == "inlineStr":
        return c.findtext(".//x:t", default="", namespaces=ns) or ""
    return c.findtext("x:v", default="", namespaces=ns) or ""


def scan_xlsx_bytes_headers(content):
    """
    Find the header row in an xlsx blob (as raw bytes).

    Looks for the first row that contains 'Product ID', 'SellerSKU',
    or 'sku.skuId' — the columns that all channel exports have in common.

    Returns the header list, or an empty list if nothing matched.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as inner:
            strings = get_shared_strings(inner)
            with inner.open("xl/worksheets/sheet1.xml") as ws:
                root = ET.parse(ws).getroot()

        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for row in root.findall(".//x:row", ns):
            cells = {}
            for c in row.findall("x:c", ns):
                ref = c.get("r", "")
                col_letter = "".join(filter(str.isalpha, ref))
                cells[col_letter] = xml_cell_val(c, strings, ns)
            vals = [v for _, v in sorted(cells.items()) if v]
            if "Product ID" in vals or "SellerSKU" in vals or "sku.skuId" in vals:
                return vals
    except Exception as e:
        print(f"    header scan error: {e}")
    return []


def scan_xlsx_bytes_headers_generic(content, max_rows=10):
    """
    Return the first non-empty row from an xlsx blob as a header list.

    Used for files like Zalora templates where we can't rely on specific
    column names — we just grab whatever the first populated row says.

    Checks all sheets and returns the first hit it finds.
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

                ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for i, row in enumerate(root.findall(".//x:row", ns)):
                    cells = {}
                    for c in row.findall("x:c", ns):
                        ref = c.get("r", "")
                        col_letter = "".join(filter(str.isalpha, ref))
                        cells[col_letter] = xml_cell_val(c, strings, ns)
                    vals = [v for _, v in sorted(cells.items()) if v]
                    if vals:
                        return vals
                    if i >= max_rows:
                        break
    except Exception as e:
        print(f"    generic header scan error: {e}")
    return []


def is_valid_sku(sku_str):
    """
    Return True if the value looks like a real inventory SKU.

    Rules we figured out from the data:
      - Must be all digits (no letters or symbols)
      - Must be 10-13 digits long
      - Must start with 1 or 2 (base SKUs start with 1, variation SKUs with 2)

    Examples:
      1000048706    -> True   (10-digit base SKU)
      2000047394003 -> True   (13-digit variation SKU)
      99999         -> False  (too short)
      ABC123        -> False  (contains letters)
    """
    s = str(sku_str).strip()
    if not s.isdigit():
        return False
    if not (s.startswith("1") or s.startswith("2")):
        return False
    return 10 <= len(s) <= 13


def merge_row(target, source):
    """
    Merge source dict into target in-place.

    If both dicts have the same key and both values look like numbers,
    they get added together (useful for combining duplicate SKU rows).
    If the values aren't numeric, the target keeps its existing value
    and the source value is ignored.
    """
    for k, v in source.items():
        if k in target:
            try:
                target[k] = float(target[k]) + float(v)
            except (TypeError, ValueError):
                pass
        else:
            target[k] = v


def brand_group(brand):
    """
    Return which warehouse group a brand belongs to.

    Returns 'PAYLESS', 'SLCI', 'SSIEBG', or 'UNKNOWN'.
    UNKNOWN means we couldn't match it and will read all Ordazzle/SAP rows
    without any warehouse filter.
    """
    if not brand:
        return "UNKNOWN"
    bl = brand.lower()
    for b in PAYLESS_BRANDS:
        if b.lower() in bl:
            return "PAYLESS"
    for b in SLCI_BRANDS:
        if b.lower() in bl:
            return "SLCI"
    for b in SSIEBG_BRANDS:
        if b.lower() in bl:
            return "SSIEBG"
    return "UNKNOWN"


def detect_brand_from_name(product_name):
    """
    Try to figure out the brand from a product display name.

    Checks longer keywords before shorter ones so 'Tommy Hilfiger' matches
    before just 'Tommy', for example.

    Returns the canonical brand name from BRAND_KEYWORD_MAP, or None.
    """
    name_lower = product_name.lower()
    for kw in sorted(BRAND_KEYWORD_MAP, key=len, reverse=True):
        if kw in name_lower:
            return BRAND_KEYWORD_MAP[kw]
    return None


def detect_brand_from_filename(file_path):
    """
    Try to figure out the brand from just the filename.

    Handles two common patterns:
      'BrandName_SellerStockTemplate_*.xlsx'
      'BrandName-SellerStockTemplate_*.xlsx'

    Falls back to scanning the whole filename for known brand keywords
    (ignoring 'price', 'lazada', etc. which aren't brand names).

    Returns the canonical brand name, or None.
    """
    base = os.path.splitext(os.path.basename(file_path))[0]
    base_low = base.lower()

    if "_sellerstocktemplate" in base_low or "-sellerstocktemplate" in base_low:
        sep = "_" if "_sellerstocktemplate" in base_low else "-"
        prefix = base.split(sep)[0].strip()
        if prefix:
            for kw, brand in sorted(BRAND_KEYWORD_MAP.items(), key=lambda x: len(x[0]), reverse=True):
                if kw in prefix.lower():
                    return brand
            return prefix

    normalized = (
        base.lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace(".", " ")
        .replace("price", " ")
        .replace("lazada", " ")
    )
    for kw in sorted(BRAND_KEYWORD_MAP, key=len, reverse=True):
        if kw in normalized:
            return BRAND_KEYWORD_MAP[kw]
    return None


def detect_brand_from_file(file_path, max_rows=100):
    """
    Peek inside a channel file and guess the brand from product names.

    Opens the xlsx (or the first xlsx inside a zip), reads up to max_rows
    data rows, and counts how often each detected brand appears.
    Returns the most common brand found, or None.

    This is slower than filename detection but more reliable for files
    where the brand name isn't in the filename.
    """
    def _scan_blob(content):
        brands = {}
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                strings = get_shared_strings(zf)
                with zf.open("xl/worksheets/sheet1.xml") as ws:
                    root = ET.parse(ws).getroot()

            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            col_map = {}
            header_found = False
            rows_read = 0

            for row in root.findall(".//x:row", ns):
                cells = {}
                for c in row.findall("x:c", ns):
                    ref = c.get("r", "")
                    letter = "".join(filter(str.isalpha, ref))
                    cells[letter] = xml_cell_val(c, strings, ns)

                if not header_found:
                    vals = set(cells.values())
                    if "Product Name" in vals or "name" in vals:
                        col_map = {lt: val for lt, val in cells.items() if val}
                        header_found = True
                    continue

                if rows_read >= max_rows:
                    break

                row_dict = {col_name: cells.get(lt, "") for lt, col_name in col_map.items()}
                pname = row_dict.get("Product Name", "").strip()
                if pname:
                    b = detect_brand_from_name(pname)
                    if b:
                        brands[b] = brands.get(b, 0) + 1
                rows_read += 1
        except Exception:
            pass
        return brands

    try:
        ext = os.path.splitext(file_path)[1].lower()
        all_brands = {}

        if ext == ".zip":
            with zipfile.ZipFile(file_path) as outer:
                xlsx_names = sorted(n for n in outer.namelist() if n.endswith(".xlsx"))
                for xname in xlsx_names[:3]:
                    with outer.open(xname) as f:
                        for b, cnt in _scan_blob(f.read()).items():
                            all_brands[b] = all_brands.get(b, 0) + cnt
        elif ext in (".xlsx", ".xls"):
            with open(file_path, "rb") as f:
                all_brands = _scan_blob(f.read())

        if all_brands:
            return max(all_brands, key=all_brands.get)
    except Exception:
        pass
    return None


def detect_channel_from_filename(file_path):
    """
    Return the channel type based on the filename.

    Returns one of:
      'Channel_Lazada'  - files starting with 'price' or containing 'lazada'
      'Channel_Zalora'  - files containing 'zalora' or 'sellerstocktemplate'
      'Channel_Shopee'  - files starting with 'mass' or containing 'shopee'
      None              - couldn't tell from the name
    """
    base = os.path.basename(file_path).lower()
    if "lazada" in base or base.startswith("price"):
        return "Channel_Lazada"
    if "zalora" in base or "sellerstocktemplate" in base:
        return "Channel_Zalora"
    if "shopee" in base or base.startswith("mass"):
        return "Channel_Shopee"
    return None


def safe_filename(brand):
    """
    Convert a brand name to something safe to use in a filename.

    Removes spaces, apostrophes, replaces '&' with 'And', and '/' with '-'.
    Example: "women'secret" -> "womensecret"
             "MakeRoom & More" -> "MakeRoomAndMore"
    """
    return (
        brand.replace(" ", "")
             .replace("'", "")
             .replace("&", "And")
             .replace("/", "-")
    )


def to_num(v):
    """
    Try to convert v to a float. Returns 0.0 if it fails for any reason.
    Useful when you have a cell value that might be a number or might be empty.
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fmt_number(val):
    """
    Format a value for display in the output Excel sheet.

    If it's a whole number (like 5.0), return it as an int (5).
    If it's fractional (like 5.5), return the float.
    If it's not numeric at all, return the original value (or empty string for None).
    """
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return val if val is not None else ""
