"""
Channel package.

The dispatcher `read_channel_file` auto-detects the channel from the filename
and delegates to the correct reader module.  Column scanners are also exposed
here for convenience.

Usage examples
--------------
# Auto-dispatch (works for any channel file):
from inventory_pkg.channels import read_channel_file
channel, brand, sku_data, warnings, cols, label = read_channel_file("MASS_Lacoste.zip")

# Call a specific reader directly:
from inventory_pkg.channels.shopee import read_shopee_file
from inventory_pkg.channels.lazada import read_lazada_file
from inventory_pkg.channels.zalora import read_zalora_file
"""
import os

from ..utils import detect_channel_from_filename

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

def read_shopee_file(file_path):
    from .shopee import read_shopee_file as _fn
    return _fn(file_path)

def read_lazada_file(file_path):
    from .lazada import read_lazada_file as _fn
    return _fn(file_path)

def read_zalora_file(file_path, **kwargs):
    from .zalora import read_zalora_file as _fn
    return _fn(file_path, **kwargs)

def scan_shopee_columns(file_paths):
    from .shopee import scan_shopee_columns as _fn
    return _fn(file_paths)

def scan_lazada_columns(file_paths):
    from .lazada import scan_lazada_columns as _fn
    return _fn(file_paths)

def scan_zalora_columns(file_paths):
    from .zalora import scan_zalora_columns as _fn
    return _fn(file_paths)

_KEY_MAP = {
    "Channel_Shopee": ("channel_shopee", "Channel — Shopee"),
    "Channel_Lazada": ("channel_lazada", "Channel — Lazada"),
    "Channel_Zalora": ("channel_zalora", "Channel — Zalora"),
}

def read_channel_file(file_path, **kwargs):
    """
    Auto-detect the channel from *file_path* and delegate to the correct reader.

    Returns
    -------
    (channel, brand, sku_data, warnings, cols, channel_label)
    """
    print(f"  Reading channel file: {os.path.basename(file_path)}")
    label = detect_channel_from_filename(file_path)

    if label == "Channel_Lazada":
        return read_lazada_file(file_path)
    elif label == "Channel_Zalora":
        return read_zalora_file(file_path, **kwargs)
    else:
        return read_shopee_file(file_path)

def scan_channel_columns_per_file(channel_files):
    """
    Scan columns grouped by channel type.

    Returns
    -------
    list of (source_key, display_label, cols) — one entry per channel type.
      source_key    : 'channel_shopee' | 'channel_lazada' | 'channel_zalora'
      display_label : 'Channel — Shopee' | … 
      cols          : ordered, deduplicated header list for that type
    """
    buckets = {}        # source_key -> [display_label, cols_list, seen_set]
    zalora_src_file = {}  # track which sellerstocktemplate file fed channel_zalora

    for file_path in channel_files:
        ch_label = detect_channel_from_filename(file_path) or "Channel_Shopee"
        src_key, disp = _KEY_MAP.get(ch_label, ("channel_shopee", "Channel — Shopee"))

        if src_key not in buckets:
            buckets[src_key] = [disp, [], set()]

        _, cols, seen = buckets[src_key]

        if ch_label == "Channel_Lazada":
            hdrs = scan_lazada_columns([file_path])
        elif ch_label == "Channel_Zalora":
            fname_low = os.path.basename(file_path).lower()
            if "sellerstocktemplate" in fname_low:
                hdrs = []
                print(f"    Channel—Zalora: skipping {os.path.basename(file_path)} (SellerStockTemplate, not used for columns)")
            else:
                hdrs = scan_zalora_columns([file_path])
                print(f"    Channel—Zalora columns: reading from {os.path.basename(file_path)}")
        else:
            hdrs = scan_shopee_columns([file_path])

        for h in hdrs:
            if h and h not in seen:
                seen.add(h)
                cols.append(h)

    # Channel—Zalora label stays clean — naming convention brand_sellerstocktemplate_* is enough
    pass

    return [(sk, entry[0], entry[1]) for sk, entry in buckets.items()]

def scan_channel_columns(channel_files):    
    """
    Return a flat, deduplicated header list across all channel files
    (regardless of channel type).
    """
    cols, seen = [], set()
    for file_path in channel_files:
        ch_label = detect_channel_from_filename(file_path) or "Channel_Shopee"

        if ch_label == "Channel_Lazada":
            hdrs = scan_lazada_columns([file_path])
        elif ch_label == "Channel_Zalora":
            # Skip sellerstocktemplate — read columns from all other Zalora files.
            if "sellerstocktemplate" in os.path.basename(file_path).lower():
                hdrs = []
            else:
                hdrs = scan_zalora_columns([file_path])
        else:
            hdrs = scan_shopee_columns([file_path])

        for h in hdrs:
            if h and h not in seen:
                seen.add(h)
                cols.append(h)
    return cols