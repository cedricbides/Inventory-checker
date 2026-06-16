"""
run_history.py

Appends one row to run_history.csv after every successful report generation.
The file is created automatically on the first run and lives in the project
root (one level above inventory_pkg/).

Columns written
---------------
  timestamp       - when the run finished (YYYY-MM-DD HH:MM)
  brand           - detected brand name
  group           - warehouse group (PAYLESS / SLCI / SSIEBG / UNKNOWN)
  channel         - Shopee / Lazada / Zalora
  total_skus      - total rows in the output sheet
  matched_ordazzle - rows that found a match in Ordazzle
  matched_sap     - rows that found a match in SAP
  output_file     - filename of the generated Excel (or 'in-memory' for web)

Usage
-----
    from inventory_pkg.run_history import append_run

    append_run(
        brand="Lacoste",
        group="SSIEBG",
        channel="Shopee",
        total_skus=320,
        matched_ord=310,
        matched_sap=305,
        output_file="Inventory_Result_Lacoste_Shopee_2026-05-17_09-00.xlsx",
    )
"""

import csv
import os
from datetime import datetime

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
HISTORY_FILE = os.path.join(_PROJECT_ROOT, "run_history.csv")

FIELDNAMES = [
    "timestamp",
    "brand",
    "group",
    "channel",
    "total_skus",
    "matched_ordazzle",
    "matched_sap",
    "output_file",
]


def append_run(brand, group, channel, total_skus, matched_ord, matched_sap, output_file):
    """
    Append a single result row to run_history.csv.

    Creates the file with a header row if it does not exist yet.
    Failures are caught silently so a logging error never breaks a run.
    """
    try:
        file_exists = os.path.isfile(HISTORY_FILE)
        with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "brand": brand,
                "group": group,
                "channel": channel,
                "total_skus": total_skus,
                "matched_ordazzle": matched_ord,
                "matched_sap": matched_sap,
                "output_file": output_file,
            })
    except Exception as exc:
        print(f"  run_history: could not write log entry — {exc}")
