"""Readers package — Ordazzle, SAP, and user-modified file readers."""

__all__ = [
    "scan_modify_columns_per_file",
    "read_ordazzle_files", "scan_ordazzle_columns",
    "read_sap_files",      "scan_sap_columns",
    "read_modify_files",   "scan_modify_columns",
]

def read_ordazzle_files(paths, warehouse_filter=None):
    from .ordazzle import read_ordazzle_files as _fn
    return _fn(paths, warehouse_filter=warehouse_filter)

def scan_ordazzle_columns(paths):
    from .ordazzle import scan_ordazzle_columns as _fn
    return _fn(paths)

def read_sap_files(paths, site_filter=None, storage_loc_filter=None):
    from .sap import read_sap_files as _fn
    return _fn(paths, site_filter=site_filter, storage_loc_filter=storage_loc_filter)

def scan_sap_columns(paths):
    from .sap import scan_sap_columns as _fn
    return _fn(paths)

def read_modify_files(paths):
    from .modify import read_modify_files as _fn
    return _fn(paths)

def scan_modify_columns(paths):
    from .modify import scan_modify_columns as _fn
    return _fn(paths)

def scan_modify_columns_per_file(paths):
    from .modify import scan_modify_columns_per_file as _fn
    return _fn(paths)