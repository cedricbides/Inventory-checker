"""
inventory_pkg — modular inventory checker.

Usage
-----
    python -m inventory_pkg          # full GUI run
    python -m inventory_pkg.main     # same

Call individual channel readers without loading the whole codebase:
    from inventory_pkg.channels.shopee import read_shopee_file
    from inventory_pkg.channels.lazada import read_lazada_file
    from inventory_pkg.channels.zalora import read_zalora_file
    from inventory_pkg.channels       import read_channel_file   # auto-dispatch

    from inventory_pkg.readers.ordazzle import read_ordazzle_files
    from inventory_pkg.readers.sap      import read_sap_files
    from inventory_pkg.readers.modify   import read_modify_files

    from inventory_pkg.output  import build_output
    from inventory_pkg.gui     import launch_gui
    from inventory_pkg.main    import run
"""
