"""
constants.py

Builds the flat brand lists, warehouse/SAP lookups, Excel fill colours,
and the Result Preview sample data that several modules share.

All the actual brand/warehouse/pattern values live in config.py.
This file just reads from there and exposes them in a convenient form.
"""

from openpyxl.styles import PatternFill
from .config import BRAND_GROUPS, BRAND_ALIASES


# Helper functions for reading from BRAND_GROUPS

def _brands_for(group_name):
    """Return the brands list for the given group name, or an empty list."""
    for group in BRAND_GROUPS:
        if group["group"] == group_name:
            return group["brands"]
    return []


def _attr_for(group_name, attr):
    """Return a specific attribute from a group, or None if not found."""
    for group in BRAND_GROUPS:
        if group["group"] == group_name:
            return group[attr]
    return None


# Per-group brand lists and warehouse/SAP constants.
# These are used in main.py to filter Ordazzle and SAP exports by group.

SSIEBG_BRANDS      = _brands_for("SSIEBG")
SSIEBG_WAREHOUSE   = _attr_for("SSIEBG", "warehouse")
SSIEBG_SAP_SITE    = _attr_for("SSIEBG", "sap_site")
SSIEBG_STORAGE_LOC = _attr_for("SSIEBG", "storage_loc")

PAYLESS_BRANDS      = _brands_for("PAYLESS")
PAYLESS_WAREHOUSE   = _attr_for("PAYLESS", "warehouse")
PAYLESS_SAP_SITE    = _attr_for("PAYLESS", "sap_site")
PAYLESS_STORAGE_LOC = _attr_for("PAYLESS", "storage_loc")

SLCI_BRANDS      = _brands_for("SLCI")
SLCI_WAREHOUSE   = _attr_for("SLCI", "warehouse")
SLCI_SAP_SITE    = _attr_for("SLCI", "sap_site")
SLCI_STORAGE_LOC = _attr_for("SLCI", "storage_loc")

# Flat list of every brand across all groups — used for keyword matching
ALL_BRANDS = [brand for group in BRAND_GROUPS for brand in group["brands"]]

# Maps lowercased brand/alias strings to their canonical brand name.
# Longer keywords are checked first (see detect_brand_from_name in utils.py).
BRAND_KEYWORD_MAP = {b.lower(): b for b in ALL_BRANDS}
BRAND_KEYWORD_MAP.update({k.lower(): v for k, v in BRAND_ALIASES.items()})


# Excel fill colours used in the output workbook

GREEN      = PatternFill("solid", fgColor="C6EFCE")   # matched / TRUE
RED        = PatternFill("solid", fgColor="FFC7CE")   # missing / FALSE
YELLOW     = PatternFill("solid", fgColor="FFEB9C")   # N/A comparison
HEADER     = PatternFill("solid", fgColor="1A2A4A")   # column header row
GRAY       = PatternFill("solid", fgColor="F2F2F2")   # alternating row
WHITE_FILL = PatternFill("solid", fgColor="FFFFFF")   # alternating row
ORANGE     = PatternFill("solid", fgColor="FFD966")   # warning banner
CMP_HDR    = PatternFill("solid", fgColor="2E4A7A")   # comparison column header


# Sample rows shown in the Result Preview sheet so the user can see
# what the expected output format looks like even before running a real file.

RESULT_PREVIEW_SAMPLE = [
    (1000048513,    1, "#N/A", "#N/A", "#N/A", "#N/A", "#N/A", "n/a"),
    (1000048706,    1, "58157771154", "435690761564", 0,  0,  1,  "TRUE"),
    (2000047394003, 1, "58157771155", "435690761565", 21, 21, 18, "TRUE"),
    (1000048845005, 1, "#N/A", "#N/A", "#N/A", "#N/A", "#N/A", "n/a"),
]

RESULT_PREVIEW_HEADERS = [
    "Base_SKU (Ordazzle)",
    "BASE_QTY (Ordazzle)",
    "CH_PRODUCT ID",
    "CH_Variation ID",
    "ORD_Inventory published",
    "CH_Stock",
    "SAP_UNRESTRICTED STOCK",
    "Ordazzle X Channel",
]

RESULT_PREVIEW_WIDTHS = [22, 20, 18, 18, 24, 12, 24, 20]
