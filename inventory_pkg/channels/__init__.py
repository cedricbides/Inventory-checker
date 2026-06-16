"""
Channel file readers — auto-dispatch by filename.

Call read_channel_file() for automatic channel detection, or import a
specific reader directly from channels.shopee / lazada / zalora.
"""

import os

from ..utils import append_unique_values, detect_channel_from_filename
from .lazada import read_lazada_file, scan_lazada_columns
from .shopee import read_shopee_file, scan_shopee_columns
from .zalora import read_zalora_file, scan_zalora_columns

__all__ = [
    "read_channel_file",
    "scan_channel_columns",
    "scan_channel_columns_per_file",
    "read_shopee_file",
    "read_lazada_file",
    "read_zalora_file",
    "scan_shopee_columns",
    "scan_lazada_columns",
    "scan_zalora_columns",
]

_KEY_MAP = {
    "Channel_Shopee": ("channel_shopee", "Channel — Shopee"),
    "Channel_Lazada": ("channel_lazada", "Channel — Lazada"),
    "Channel_Zalora": ("channel_zalora", "Channel — Zalora"),
}


def _scan_headers_for_channel_file(file_path, ch_label):
    if ch_label == "Channel_Lazada":
        return scan_lazada_columns([file_path])
    if ch_label == "Channel_Zalora":
        if "sellerstocktemplate" in os.path.basename(file_path).lower():
            print(f"    Channel—Zalora: skipping {os.path.basename(file_path)} "
                  f"(SellerStockTemplate, not used for columns)")
            return []
        print(f"    Channel—Zalora columns: reading from {os.path.basename(file_path)}")
        return scan_zalora_columns([file_path])
    return scan_shopee_columns([file_path])


def read_channel_file(file_path, **kwargs):
    """Auto-detect channel from filename and read the file."""
    print(f"  Reading channel file: {os.path.basename(file_path)}")
    label = detect_channel_from_filename(file_path)
    readers = {
        "Channel_Lazada": lambda: read_lazada_file(file_path),
        "Channel_Zalora": lambda: read_zalora_file(file_path, **kwargs),
    }
    return readers.get(label, lambda: read_shopee_file(file_path))()


def scan_channel_columns_per_file(channel_files):
    """Scan columns grouped by channel type."""
    buckets = {}

    for file_path in channel_files:
        ch_label = detect_channel_from_filename(file_path) or "Channel_Shopee"
        src_key, disp = _KEY_MAP.get(ch_label, ("channel_shopee", "Channel — Shopee"))

        if src_key not in buckets:
            buckets[src_key] = [disp, [], set()]

        _, cols, seen = buckets[src_key]
        append_unique_values(cols, seen, _scan_headers_for_channel_file(file_path, ch_label))

    return [(sk, entry[0], entry[1]) for sk, entry in buckets.items()]


def scan_channel_columns(channel_files):
    """Return a flat, deduplicated header list across all channel files."""
    cols, seen = [], set()
    for file_path in channel_files:
        ch_label = detect_channel_from_filename(file_path) or "Channel_Shopee"
        append_unique_values(cols, seen, _scan_headers_for_channel_file(file_path, ch_label))
    return cols
