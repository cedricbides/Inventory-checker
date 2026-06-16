"""
inventory_pkg - modular inventory checker (web app).

Core modules:
    from inventory_pkg.channels.shopee  import read_shopee_file
    from inventory_pkg.channels.lazada  import read_lazada_file
    from inventory_pkg.channels.zalora  import read_zalora_file
    from inventory_pkg.channels         import read_channel_file

    from inventory_pkg.readers.ordazzle import read_ordazzle_files
    from inventory_pkg.readers.sap      import read_sap_files

    from inventory_pkg.output           import build_output
    from inventory_pkg.run_history      import append_run
"""
