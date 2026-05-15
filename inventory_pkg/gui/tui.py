"""
Terminal UI replacement for the tkinter GUI.

Drop-in for gui/app.py — same function signature, same return value.

Usage
-----
Set the environment variable before running:
    USE_GUI=1 python -m inventory_pkg   # force tkinter (original)
    USE_GUI=0 python -m inventory_pkg   # force terminal  (this file)

If USE_GUI is not set, it defaults to terminal (0).

Dependencies (pip install):
    questionary
    rich
"""

import os
import sys

def launch_gui(
    channel_files, ordazzle_files, sap_files,
    channel_cols, ordazzle_cols, sap_cols,
    suggested_base=None,
    modify_files=None,
    modify_files_list=None,
    modify_cols=None,
    channel_sources=None,
    file_brand_map=None,
    modify_cols_per_file=None,
):
    """
    Router: launches tkinter GUI or terminal UI depending on USE_GUI env var.

    Returns
    -------
    (output_cols, comparisons, base, selected_files, zalora_options)
    or (None, None, None, None, None) on cancel.
    """
    use_gui = os.environ.get("USE_GUI", "0").strip() not in ("0", "false", "no", "")

    if use_gui:
        try:
            from .app import launch_gui as _tk_launch
            return _tk_launch(
                channel_files, ordazzle_files, sap_files,
                channel_cols, ordazzle_cols, sap_cols,
                suggested_base=suggested_base,
                modify_files=modify_files,
                modify_files_list=modify_files_list,
                modify_cols=modify_cols,
                channel_sources=channel_sources,
                file_brand_map=file_brand_map,
                modify_cols_per_file=modify_cols_per_file,
            )
        except Exception as e:
            import traceback
            print(f"\n[ERROR] tkinter GUI failed — falling back to terminal UI.")
            print(f"  Reason: {e}")
            traceback.print_exc()
            print()

    return _launch_tui(
        channel_files, ordazzle_files, sap_files,
        channel_cols, ordazzle_cols, sap_cols,
        suggested_base=suggested_base,
        modify_files=modify_files,
        modify_files_list=modify_files_list,
        modify_cols=modify_cols,
        channel_sources=channel_sources,
        file_brand_map=file_brand_map,
    )

def _launch_tui(
    channel_files, ordazzle_files, sap_files,
    channel_cols, ordazzle_cols, sap_cols,
    suggested_base=None,
    modify_files=None,
    modify_files_list=None,
    modify_cols=None,
    channel_sources=None,
    file_brand_map=None,
    modify_cols_per_file=None,
):
    try:
        import questionary
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich import box
    except ImportError:
        print("\n[!] Install deps first:  pip install questionary rich\n")
        sys.exit(1)

    try:
        from ..config import QUICK_EXPORT_COLUMNS as QE_REQUIRED, APP as _APP_CFG
    except ImportError:
        QE_REQUIRED = {
            "ch_sku":   ("channel",  ["SKU", "SellerSKU", "Parent SKU", "seller_sku"]),
            "ch_stock": ("channel",  ["Stock", "Available Stock", "quantity", "Quantity"]),
            "ord_inv":  ("ordazzle", ["INV TO PUBLISHED STOCK", "PUBLISHED STOCK",
                                      "Inventory published"]),
            "ch_pid":   ("channel",  ["Product ID"]),
            "ch_var":   ("channel",  ["Variation ID", "sku.skuId", "SKU Reference No."]),
        }
        _APP_CFG = {}

    if modify_files      is None: modify_files      = []
    if modify_files_list is None: modify_files_list = []
    if modify_cols       is None: modify_cols       = []
    if file_brand_map    is None: file_brand_map    = {}

    console = Console()

    console.print(Panel.fit(
        "[bold cyan]INVENTORY CHECKER[/bold cyan]  [dim]terminal mode[/dim]\n"
        "[dim]Set [bold]USE_GUI=1[/bold] to switch back to the tkinter window.[/dim]",
        border_style="cyan",
    ))

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    t.add_column("Source", style="cyan")
    t.add_column("Files")
    t.add_row("Channel",  ", ".join(os.path.basename(f) for f in channel_files)  or "—")
    t.add_row("Ordazzle", ", ".join(os.path.basename(f) for f in ordazzle_files) or "—")
    t.add_row("SAP",      ", ".join(os.path.basename(f) for f in sap_files)      or "—")
    if modify_files_list:
        t.add_row("Modify", ", ".join(os.path.basename(f) for f in modify_files_list))
    console.print(t)

    ABBR = {
        "channel": "CH", "channel_shopee": "CH·SP",
        "channel_lazada": "CH·LZ", "channel_zalora": "CH·ZL",
        "ordazzle": "ORD", "sap": "SAP", "modify": "MOD",
    }

    def fmt(src, col):
        return f"[{ABBR.get(src, src)}] {col}"

    # Build full source-col list
    all_src_cols = []
    if channel_sources:
        for sk, _, cols in channel_sources:
            all_src_cols.extend([(sk, c) for c in cols])
    else:
        all_src_cols.extend([("channel", c) for c in channel_cols])
    all_src_cols += (
        [("ordazzle", c) for c in ordazzle_cols] +
        [("sap",      c) for c in sap_cols]      +
        [("modify",   c) for c in modify_cols]
    )

    # QE_REQUIRED is imported from config.py (QUICK_EXPORT_COLUMNS)

    def _resolve_qe_col(src_key, candidates, ch_src_key=None):
        """Return (src, col) for the first matching candidate, or None."""
        if src_key == "channel":
            if channel_sources:
                for sk, _, cols in channel_sources:
                    if ch_src_key and sk != ch_src_key:
                        continue
                    for c in candidates:
                        if c in cols:
                            return (sk, c)
            else:
                for c in candidates:
                    if c in channel_cols:
                        return ("channel", c)
        elif src_key == "ordazzle":
            for c in candidates:
                if c in ordazzle_cols:
                    return ("ordazzle", c)
        elif src_key == "sap":
            for c in candidates:
                if c in sap_cols:
                    return ("sap", c)
        elif src_key == "modify":
            for c in candidates:
                if c in modify_cols:
                    return ("modify", c)
        return None

    def _run_quick_export_steps_4_5(sel_cols, cmp_list, base):
        """Shared file-selection logic for Quick Export (steps 4 & 5)."""
        selected_files = None
        zalora_options = {"extract_mpid": True, "extract_mpskuid": True,
                          "zalora_file_brands": {}, "modify_zalora_brands": {}}
        try:
            from .zalora_options import ZALORA_CRED_BRANDS
        except ImportError:
            ZALORA_CRED_BRANDS = []

        console.print("\n[bold]Step 4 of 5 — Channel / Brand Files[/bold]")

        if file_brand_map:
            channel_map = {fp: v for fp, v in file_brand_map.items() if v[1] != "Modify"}
            modify_map  = {fp: v for fp, v in file_brand_map.items() if v[1] == "Modify"}

            if channel_map:
                ch_choices = []
                for fp, (brand, ch_short) in channel_map.items():
                    label = f"{brand}  [{ch_short}]  ({os.path.basename(fp)})"
                    ch_choices.append(questionary.Choice(title=label, value=fp, checked=True))
                picked_ch = questionary.checkbox(
                    "Select channel/marketplace files to generate:",
                    choices=ch_choices,
                ).ask()
                if picked_ch is None:
                    return None, None, None, None, None
                if not picked_ch:
                    console.print("[red]No channel files selected — exiting.[/red]")
                    return None, None, None, None, None
                selected_files = picked_ch
            else:
                selected_files = []

            for fp in (selected_files or []):
                base_name = os.path.basename(fp).lower()
                if "sellerstocktemplate" in base_name and ZALORA_CRED_BRANDS:
                    console.print(f"  [cyan]Zalora channel file:[/cyan] {os.path.basename(fp)}")
                    brand_pick = questionary.select(
                        "  Assign Zalora brand credential:",
                        choices=ZALORA_CRED_BRANDS,
                    ).ask()
                    if brand_pick is None:
                        return None, None, None, None, None
                    zalora_options["zalora_file_brands"][fp] = brand_pick

            if modify_map:
                console.print("\n[bold]Step 5 of 5 — Modify Files[/bold]")
                mod_choices = []
                for fp, (brand, _) in modify_map.items():
                    label = f"{brand}  ({os.path.basename(fp)})"
                    mod_choices.append(questionary.Choice(title=label, value=fp, checked=True))
                picked_mod = questionary.checkbox(
                    "Select Modify files to include:",
                    choices=mod_choices,
                ).ask()
                if picked_mod is None:
                    return None, None, None, None, None
                selected_files = (selected_files or []) + picked_mod

                for fp in picked_mod:
                    base_name = os.path.basename(fp).lower()
                    is_zalora_mod = "zalora" in base_name
                    if not is_zalora_mod and ZALORA_CRED_BRANDS:
                        is_zalora_mod = questionary.confirm(
                            f"  Is '{os.path.basename(fp)}' a Zalora modify file?",
                            default=False,
                        ).ask()
                        if is_zalora_mod is None:
                            return None, None, None, None, None
                    if is_zalora_mod and ZALORA_CRED_BRANDS:
                        console.print(f"  [cyan]Zalora modify file:[/cyan] {os.path.basename(fp)}")
                        brand_pick = questionary.select(
                            "  Assign Zalora brand credential:",
                            choices=["None"] + ZALORA_CRED_BRANDS,
                            default="None",
                        ).ask()
                        if brand_pick is None:
                            return None, None, None, None, None
                        if brand_pick != "None":
                            zalora_options["modify_zalora_brands"][fp] = brand_pick
            else:
                console.print("\n[bold]Step 5 of 5 — Modify Files[/bold]")
                console.print("  [dim]No Modify files detected.[/dim]")
        else:
            console.print("  [dim]No multi-brand file map — generating for all files.[/dim]")
            console.print("\n[bold]Step 5 of 5 — Modify Files[/bold]")
            console.print("  [dim]No Modify files detected.[/dim]")

        base_display = (
            ", ".join(f"{k}→{v}" for k, v in base.items())
            if isinstance(base, dict) else base
        )
        console.print()
        console.print(Panel(
            f"[bold]Output columns :[/bold] {len(sel_cols)}\n"
            f"[bold]Comparisons    :[/bold] {len(cmp_list)}\n"
            f"[bold]Base SKU       :[/bold] {base_display}\n"
            f"[bold]Files          :[/bold] {len(selected_files) if selected_files else 'all'}",
            title="[green]Ready to run[/green]",
            border_style="green",
        ))
        confirm = questionary.confirm("Proceed?", default=True).ask()
        if not confirm:
            return None, None, None, None, None
        return sel_cols, cmp_list, base, selected_files, zalora_options

    # Ask user whether to use Quick Export
    console.print(
        "\n[bold cyan]⚡ Quick Export[/bold cyan]  "
        "[dim]auto-selects: SKU | Stock | INV TO PUBLISHED STOCK "
        "| Product ID | Variation ID + Comparison[/dim]"
    )
    use_qe = questionary.confirm(
        "Use Quick Export? (No = manual column selection)",
        default=True,
    ).ask()
    if use_qe is None:
        return None, None, None, None, None

    if use_qe:
        ch_sources_to_use = (
            [(sk, dl, cols) for sk, dl, cols in channel_sources]
            if channel_sources else [("channel", "Channel", channel_cols)]
        )
        _multi_ch_qe = bool(channel_sources and len(channel_sources) > 1)

        # Validate required columns
        all_errors = []
        for ch_src_key, ch_disp, _ in ch_sources_to_use:
            missing = []
            for qe_key, (src_key, candidates) in QE_REQUIRED.items():
                found = _resolve_qe_col(src_key, candidates, ch_src_key)
                if not found:
                    src_label = ch_disp if src_key == "channel" else src_key.capitalize()
                    missing.append(f"  • {candidates[0]}  [{src_label}]")
            if missing:
                all_errors.append(f"{ch_disp}:\n" + "\n".join(missing))

        if all_errors:
            console.print("[red]⚡ Quick Export — missing required columns:[/red]")
            for err in all_errors:
                console.print(f"[red]{err}[/red]")
            console.print("[dim]Falling back to manual column selection.[/dim]\n")
        else:
            qe_sel_cols = []
            qe_cmp_list = []
            qe_base     = {} if _multi_ch_qe else None

            for ch_src_key, ch_disp, _ in ch_sources_to_use:
                ch_sku_e   = _resolve_qe_col("channel",  QE_REQUIRED["ch_sku"][1],   ch_src_key)
                ch_stock_e = _resolve_qe_col("channel",  QE_REQUIRED["ch_stock"][1], ch_src_key)
                ord_inv_e  = _resolve_qe_col("ordazzle", QE_REQUIRED["ord_inv"][1])
                ch_pid_e   = _resolve_qe_col("channel",  QE_REQUIRED["ch_pid"][1],   ch_src_key)
                ch_var_e   = _resolve_qe_col("channel",  QE_REQUIRED["ch_var"][1],   ch_src_key)

                for entry in [ch_sku_e, ch_stock_e, ord_inv_e, ch_pid_e, ch_var_e]:
                    if entry and list(entry) not in qe_sel_cols:
                        qe_sel_cols.append(list(entry))

                if ch_stock_e and ord_inv_e:
                    ch_abbr = {
                        "channel_shopee": "CH·SP", "channel_lazada": "CH·LZ",
                        "channel_zalora": "CH·ZL", "channel": "CH",
                    }.get(ch_stock_e[0], "CH")
                    lbl = f"[{ch_abbr}] {ch_stock_e[1]} × [ORD] {ord_inv_e[1]}"
                    qe_cmp_list.append([
                        ch_stock_e[0], ch_stock_e[1],
                        ord_inv_e[0],  ord_inv_e[1],
                        lbl,
                    ])

                if _multi_ch_qe:
                    qe_base[ch_src_key] = ch_src_key
                else:
                    qe_base = channel_sources[0][0] if channel_sources else "channel"

            return _run_quick_export_steps_4_5(qe_sel_cols, qe_cmp_list, qe_base)
    # ── End Quick Export ─────────────────────────────────────────────────────────

    console.print("\n[bold]Step 1 of 5 — Output Columns[/bold]")
    # Group by source for nicer display
    from collections import defaultdict
    groups = defaultdict(list)
    for sc in all_src_cols:
        groups[sc[0]].append(sc)

    choices = []
    for src, items in groups.items():
        choices.append(questionary.Separator(f"── {ABBR.get(src, src)} ──"))
        for sc in items:
            choices.append(questionary.Choice(title=fmt(*sc), value=sc))

    picked = questionary.checkbox(
        "Select output columns  [space=toggle, a=all, i=invert, enter=confirm]:",
        choices=choices,
    ).ask()
    if picked is None:
        return None, None, None, None, None
    sel_cols = picked

    if not sel_cols:
        console.print("[red]No columns selected — exiting.[/red]")
        return None, None, None, None, None

    console.print("\n[bold]Step 2 of 5 — Base SKU Source[/bold]")

    _multi_ch = bool(channel_sources and len(channel_sources) > 1)

    if _multi_ch:
        base = {}
        for sk, label, _ in channel_sources:
            # truncate long label (e.g. long filenames in Channel — Zalora label)
            short_label = label.split("(")[0].strip()
            choices = [sk, "ordazzle", "sap"] + (["modify"] if modify_cols else [])
            answer = questionary.select(
                f"Base SKU source for [{short_label}]:",
                choices=choices,
                default=sk,
            ).ask()
            if answer is None:
                return None, None, None, None, None
            base[sk] = answer
    else:
        src_choices = ["channel", "ordazzle", "sap"] + (["modify"] if modify_cols else [])
        base = questionary.select(
            "Base SKU source:",
            choices=src_choices,
            default=suggested_base or _APP_CFG.get("default_base_sku", "channel"),
        ).ask()
        if base is None:
            return None, None, None, None, None

    console.print("\n[bold]Step 3 of 5 — Comparisons[/bold]  [dim](optional)[/dim]")
    cmp_list = []

    all_labels = [fmt(*sc) for sc in all_src_cols]

    while True:
        add = questionary.confirm(
            f"Add a comparison? ({len(cmp_list)} so far)",
            default=False,
        ).ask()
        if not add:
            break

        lchoice = questionary.select("LEFT column:",  choices=all_labels).ask()
        if lchoice is None: break
        rchoice = questionary.select("RIGHT column:", choices=all_labels).ask()
        if rchoice is None: break

        lsc = all_src_cols[all_labels.index(lchoice)]
        rsc = all_src_cols[all_labels.index(rchoice)]

        label = questionary.text(
            "Label for this comparison (leave blank to auto-generate):",
            default="",
        ).ask()
        if label is None: break
        if not label.strip():
            label = f"{lsc[1]} vs {rsc[1]}"

        cmp_list.append((lsc[0], lsc[1], rsc[0], rsc[1], label.strip()))
        console.print(f"  [green]✓[/green] Added: [dim]{label}[/dim]")

    return _run_quick_export_steps_4_5(sel_cols, cmp_list, base)