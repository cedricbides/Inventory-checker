"""
config.py  —  All user settings live here.

This is the only file you need to edit for brand/folder/pattern settings.
Zalora API credentials live in credentials.py (gitignored) to keep secrets
out of version control.

Sections
--------
  1. BRAND_GROUPS       - which brands belong to each warehouse group
  2. BRAND_ALIASES      - alternate spellings that map to a canonical brand name
  3. ZALORA_CREDENTIALS - imported from credentials.py (see that file to add/edit keys)
  4. FOLDERS            - subfolder names the tool creates in the working directory
  5. FILE_PATTERNS      - how the tool figures out which file belongs to which source
  6. OUTPUT             - result filename prefix and timestamp format
  7. APP                - UI mode and default base SKU source
  8. QUICK_EXPORT_COLUMNS - which columns Quick Export pre-selects (TUI mode only)
"""

from .credentials import ZALORA_CREDENTIALS  # noqa: F401 — re-exported for other modules


# 1. BRAND GROUPS
# Each group has a list of brands, a warehouse name, a SAP site code,
# and a storage location code. The warehouse/site/loc values are used
# to filter the Ordazzle and SAP exports so you only get rows for that group.

BRAND_GROUPS = [
    {
        "group": "SSIEBG",
        "warehouse": "SSIEBG_WH_EBGWarehouse",
        "sap_site": "2W06",
        "storage_loc": "0002",
        "brands": [
            "Springfield",
            "Cortefiel",
            "MakeRoom",
            "MakeRoom & More",
            "DKNY",
            "Dune London",
            "Pazzion",
            "Macarena",
            "Nine West",
            "Polo Ralph Lauren",
            "Pomelo",
            "Lacoste",
            "women'secret",
            "womensecret",
            "Lush",
            "Calvin Klein",
            "Tommy Hilfiger",
            "Clarks",
            "Superga",
            "FFW",
        ],
    },
    {
        "group": "PAYLESS",
        "warehouse": "Payless_WH_Warehouse",
        "sap_site": "30W9",
        "storage_loc": "0002",
        "brands": ["Payless", "Payless ShoeSource", "Payless Shoes"],
    },
    {
        "group": "SLCI",
        "warehouse": "SLCI_WH_Warehouse",
        "sap_site": "36W2",
        "storage_loc": "0002",
        "brands": ["Old Navy", "Gap", "Banana", "Banana Republic"],
    },
]


# 2. BRAND ALIASES
# Maps alternate spellings / partial names to the canonical brand name above.
# Keys are lowercased — no need to match case exactly.

BRAND_ALIASES = {
    "banana": "Banana Republic",
    "banana republic": "Banana Republic",
    "calvin": "Calvin Klein",
    "calvin klein": "Calvin Klein",
    "clarks": "Clarks",
    "cortefiel": "Cortefiel",
    "dune": "Dune London",
    "dune london": "Dune London",
    "lush": "Lush",
    "macarena": "Macarena",
    "make room": "MakeRoom & More",
    "makeroom": "MakeRoom & More",
    "nine west": "Nine West",
    "old navy": "Old Navy",
    "oldnavy": "Old Navy",
    "payless shoes": "Payless",
    "payless shoesource": "Payless",
    "pazzion": "Pazzion",
    "polo ralph": "Polo Ralph Lauren",
    "pomelo": "Pomelo",
    "ralph lauren": "Polo Ralph Lauren",
    "springfield": "Springfield",
    "superga": "Superga",
    "tommy": "Tommy Hilfiger",
    "tommy hilfiger": "Tommy Hilfiger",
    "women'secret": "women'secret",
    "womens secret": "women'secret",
    "womensecret": "women'secret",
}


# 3. ZALORA API CREDENTIALS
# Defined in credentials.py (gitignored) and imported above.
# See that file to add or change API keys per brand.


# 4. FOLDERS
# Subfolder names that the tool creates inside your working directory.
# You can rename them here if needed — just make sure the files you drop in
# match the new folder name.

FOLDERS = {
    "shopee": "Shopee",
    "lazada": "Lazada",
    "zalora": "Zalora",
    "ordazzle": "Ordazzle",
    "sap": "SAP",
    "modify": "Modify",
    "result": "RESULT",
}


# 5. FILE PATTERNS
# These are the filename prefixes (lowercased) that tell the tool what type
# a file is. For example, any file starting with "mass" or "shopee" is treated
# as a Shopee channel export.

FILE_PATTERNS = {
    "shopee_prefixes": ["mass", "shopee"],
    "lazada_prefixes": ["price", "lazada"],
    "zalora_prefixes": ["zalora"],
    "zalora_keywords": ["sellerstocktemplate"],
    "zalora_csv_prefixes": ["zalorastock"],
    "ordazzle_prefixes": ["exl", "exp"],
    "sap_prefixes": ["article"],
    "modify_prefixes": ["modify"],
}


# 6. OUTPUT SETTINGS
# Controls the filename of the generated Excel results.
# The final name looks like:  {file_prefix}{BrandName}_{Channel}_{timestamp}.xlsx

OUTPUT = {
    "file_prefix": "Inventory_Result_",
    "timestamp_format": "%Y-%m-%d_%H-%M",
}


# 7. APP SETTINGS
# use_gui: set to True to launch the tkinter window, False for terminal mode.
# default_base_sku: which data source the rows iterate from ('channel', 'ordazzle', 'sap').
# enable_quick_export: whether the Quick Export sheet is added to the output workbook.

APP = {
    "use_gui": False,
    "default_base_sku": "channel",
    "enable_quick_export": True,
}


# 8. QUICK EXPORT COLUMNS  (terminal / TUI mode only)
# Maps a short key to (source, [possible column names]).
# The tool picks the first column name from the list that actually exists in the file.

QUICK_EXPORT_COLUMNS = {
    "ch_sku":   ("channel",   ["SKU", "SellerSKU", "Parent SKU", "seller_sku"]),
    "ch_stock": ("channel",   ["Stock", "Available Stock", "quantity", "Quantity"]),
    "ch_pid":   ("channel",   ["Product ID"]),
    "ch_var":   ("channel",   ["Variation ID", "sku.skuId", "SKU Reference No."]),
    "ord_inv":  ("ordazzle",  ["INV TO PUBLISHED STOCK", "PUBLISHED STOCK", "Inventory published"]),
}