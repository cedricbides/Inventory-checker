"""
Tkinter GUI for column selection, comparison configuration, and result preview.

Public API
----------
launch_gui(channel_files, ordazzle_files, sap_files,
           channel_cols, ordazzle_cols, sap_cols,
           suggested_base, modify_files, modify_files_list,
           modify_cols, channel_sources)
    -> (selected_output_cols, comparisons, base_sku)
       or (None, None, None) if the user cancels
"""
from ..utils import detect_channel_from_filename
from ..constants import RESULT_PREVIEW_HEADERS, RESULT_PREVIEW_SAMPLE

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
    Launch the two-tab (+ preview) tkinter GUI.

    Tab 1 — Choose which columns to include in output.
    Tab 2 — Define flexible comparisons between any two columns from any source.
    Tab 3 — Result preview showing expected output layout.

    Parameters
    ----------
    channel_files     : list[str]
    ordazzle_files    : list[str]
    sap_files         : list[str]
    channel_cols      : list[str]   – flat list of all channel headers
    ordazzle_cols     : list[str]
    sap_cols          : list[str]
    suggested_base    : str | None  – 'channel' | 'ordazzle' | 'sap' | 'modify'
    modify_files      : list[(path, detected_source)] | None
    modify_files_list : list[str] | None
    modify_cols       : list[str] | None
    channel_sources   : list[(src_key, display_label, cols)] | None
    file_brand_map    : dict[str, (brand, channel_short)] | None

    Returns
    -------
    selected_output_cols : list[(source, col_name)] | None
    comparisons          : list[(lsrc, lcol, rsrc, rcol, label)] | None
    base_sku             : str | None
    selected_files       : list[str] | None
    """
    if modify_files      is None: modify_files      = []
    if modify_files_list is None: modify_files_list = []
    if modify_cols           is None: modify_cols           = []
    if file_brand_map        is None: file_brand_map        = {}
    if modify_cols_per_file  is None: modify_cols_per_file  = {}

    # Build a lookup: source -> list of modify file basenames
    modify_by_src = {}
    for fpath, fsrc in modify_files:
        import os
        modify_by_src.setdefault(fsrc, []).append(os.path.basename(fpath))

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("tkinter not available — using defaults.")
        out = []
        if channel_sources:
            for sk, _, cols in channel_sources:
                out.extend([(sk, c) for c in cols])
        else:
            out.extend([("channel", c) for c in channel_cols])
        out += (
            [("ordazzle", c) for c in ordazzle_cols] +
            [("sap",      c) for c in sap_cols]      +
            [("modify",   c) for c in modify_cols]
        )
        return out, [], suggested_base or "channel"

    import os
    from .zalora_options import ZALORA_CRED_BRANDS
    result = {"output_cols": None, "comparisons": None, "base": None,
              "selected_files": None, "zalora_options": {}}
    mod_marketplace_vars = {}   # fp -> StringVar (marketplace choice per modify file)

    DARK_BLUE  = "#1A2A4A"
    MID_BLUE   = "#2E4A7A"
    ACCENT     = "#F5A623"
    WHITE      = "#FFFFFF"
    LIGHT_GRAY = "#F0F0F0"
    BORDER_CLR = "#DDDDDD"
    GROUP_BG   = "#FAFAFA"
    SRC_COLORS = {
        "channel":         "#2C6E8A",
        "channel_shopee":  "#2C6E8A",
        "channel_lazada":  "#1A5F7A",
        "channel_zalora":  "#0D4D6A",
        "ordazzle": "#5A4A8A", "sap": "#2A6A4A", "modify": "#8B5E00",
    }

    def _src_color(src):
        """Return display color for a src key, handling modify_N aliases."""
        if src not in SRC_COLORS and src.startswith("modify"):
            return SRC_COLORS["modify"]
        return SRC_COLORS.get(src, DARK_BLUE)

    root = tk.Tk()
    root.title("Inventory Checker – Column & Comparison Settings")
    root.resizable(True, True)
    root.configure(bg="#F4F4F4")
    root.geometry("860x860")
    root.minsize(720, 640)

    sel_cols   = []   # start empty — user selects what they need
    cmp_list   = []
    check_vars = {}   # (src, col) -> BooleanVar

    # If multiple channel marketplaces are present, give each its own base var
    _multi_ch = bool(channel_sources and len(channel_sources) > 1)
    if _multi_ch:
        base_vars = {
            sk: tk.StringVar(value=suggested_base if suggested_base == sk else sk)
            for sk, _, _ in channel_sources
        }
        base_var = None  # unused in multi-ch mode
    else:
        base_var  = tk.StringVar(value=suggested_base or "channel")
        base_vars = None

    def fmt_src_col(src, col):
        abbr = {
            "channel": "CH", "channel_shopee": "CH·SP", "channel_lazada": "CH·LZ",
            "channel_zalora": "CH·ZL", "ordazzle": "ORD", "sap": "SAP", "modify": "MOD",
        }.get(src, src)
        return f"[{abbr}] {col}"

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
    all_src_labels = [fmt_src_col(s, c) for s, c in all_src_cols]

    topbar = tk.Frame(root, bg=DARK_BLUE, height=44)
    topbar.pack(fill="x")
    topbar.pack_propagate(False)
    tk.Label(topbar, text="Inventory Checker", bg=DARK_BLUE, fg=WHITE,
             font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=10)
    tk.Label(topbar, text="Column & Comparison Settings", bg=DARK_BLUE, fg="#99AACC",
             font=("Segoe UI", 9)).pack(side="left", padx=4, pady=10)

    style = ttk.Style()
    style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=[12, 4])
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=6)

    # TAB 1 – Output Columns
    tab1 = tk.Frame(nb, bg="#F4F4F4")
    nb.add(tab1, text="  Output Columns  ")

    cv1 = tk.Canvas(tab1, bg="#F4F4F4", highlightthickness=0)
    sb1 = tk.Scrollbar(tab1, orient="vertical", command=cv1.yview)
    cv1.configure(yscrollcommand=sb1.set)
    sb1.pack(side="right", fill="y")
    cv1.pack(side="left", fill="both", expand=True)
    inner1 = tk.Frame(cv1, bg="#F4F4F4")
    win1   = cv1.create_window((0, 0), window=inner1, anchor="nw")
    inner1.bind("<Configure>", lambda e: cv1.configure(scrollregion=cv1.bbox("all")))
    cv1.bind("<Configure>",   lambda e: cv1.itemconfig(win1, width=e.width))
    cv1.bind_all("<MouseWheel>",
                 lambda e: cv1.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    # Files detected panel
    ff = tk.LabelFrame(inner1, text=" Files Detected ", bg=WHITE,
                       font=("Segoe UI", 9, "bold"), fg=DARK_BLUE, padx=10, pady=6)
    ff.pack(fill="x", padx=12, pady=(12, 6))

    modify_paths  = {fpath for fpath, _ in modify_files}
    src_file_map  = [
        ("Channel",  channel_files),
        ("Ordazzle", ordazzle_files),
        ("SAP",      sap_files),
        ("Modify",   modify_files_list),
    ]
    for label, files in src_file_map:
        row      = tk.Frame(ff, bg=WHITE)
        row.pack(fill="x", pady=1)
        lbl_color = "#8B5E00" if label == "Modify" else MID_BLUE
        tk.Label(row, text=f"{label}:", width=10, anchor="w",
                 font=("Segoe UI", 9, "bold"), bg=WHITE, fg=lbl_color).pack(side="left")
        if not files:
            tk.Label(row,
                     text="None" if label == "Modify" else "Not found",
                     anchor="w",
                     font=("Segoe UI", 9), bg=WHITE,
                     fg="#999999" if label == "Modify" else "#CC0000").pack(side="left", padx=4)
        else:
            file_frame = tk.Frame(row, bg=WHITE)
            file_frame.pack(side="left", fill="x", padx=4)
            for fpath in files:
                bname  = os.path.basename(fpath)
                is_mod = fpath in modify_paths or label == "Modify"
                f_row  = tk.Frame(file_frame, bg=WHITE)
                f_row.pack(anchor="w")
                tk.Label(f_row, text=bname,
                         font=("Segoe UI", 9, "bold" if is_mod else "normal"),
                         bg=WHITE,
                         fg="#B8560A" if is_mod else "#333333").pack(side="left")
                if is_mod:
                    tk.Label(f_row, text=" ✎ user-modified",
                             font=("Segoe UI", 8, "italic"),
                             bg="#FFF8E7", fg="#8B5E00",
                             padx=4, pady=1, relief="flat").pack(side="left", padx=(4, 0))

    _deferred_cmp_refresh = []   # filled once refresh_cmp_display is defined (Tab 2)

    brand_file_vars    = {}   # file_path -> BooleanVar
    _zst_brand_labels  = {}   # file_path -> Label  (SellerStockTemplate only)
    modify_zalora_vars = {}   # file_path -> StringVar  (Modify rows only)
    zalora_file_vars   = {}   # file_path -> StringVar  (Zalora channel rows only)

    if file_brand_map:
        channel_map = {fp: v for fp, v in file_brand_map.items() if v[1] != "Modify"}
        modify_map  = {fp: v for fp, v in file_brand_map.items() if v[1] == "Modify"}

        def _make_file_row(parent, fp, brand_name, ch_short, is_modify=False):
            """Build one checkbox row; returns the BooleanVar."""
            var = tk.BooleanVar(value=True)
            brand_file_vars[fp] = var
            row = tk.Frame(parent, bg=WHITE)
            row.pack(anchor="w", pady=1)

            dot_color = {
                "Shopee": "#EE4D2D", "Lazada": "#0F146D", "Zalora": "#2D2D2D",
                "Modify": "#8B5E00",
            }.get(ch_short, "#555555")

            _is_zst = "sellerstocktemplate" in os.path.basename(fp).lower()

            tk.Checkbutton(row, variable=var, bg=WHITE,
                           activebackground=WHITE).pack(side="left")
            tk.Label(row, text="●", font=("Segoe UI", 9), bg=WHITE,
                     fg=dot_color).pack(side="left")
            lbl = tk.Label(row,
                     text=f" {brand_name}",
                     font=("Segoe UI", 9, "bold"), bg=WHITE,
                     fg="#CC6600" if _is_zst else ("#8B5E00" if is_modify else DARK_BLUE))
            lbl.pack(side="left")
            if _is_zst:
                _zst_brand_labels[fp] = lbl
            if not is_modify:
                tk.Label(row, text=f"  —  {ch_short}",
                         font=("Segoe UI", 9), bg=WHITE, fg="#666666").pack(side="left")
            tk.Label(row, text=f"  ({os.path.basename(fp)})",
                     font=("Segoe UI", 8), bg=WHITE, fg="#999999").pack(side="left")

            # Zalora CHANNEL file (SellerStockTemplate) → brand credential dropdown
            if _is_zst:
                zalora_file_vars[fp] = tk.StringVar(value="")
                tk.Label(row, text="  Zalora Brand:",
                         font=("Segoe UI", 8), bg=WHITE,
                         fg="#0D4D6A").pack(side="left", padx=(8, 0))
                ttk.Combobox(row, textvariable=zalora_file_vars[fp],
                             values=ZALORA_CRED_BRANDS,
                             state="readonly", width=20,
                             font=("Segoe UI", 8)).pack(side="left", padx=(2, 0))

            # Modify file → user declares marketplace, then brand if Zalora
            if is_modify:
                mod_marketplace_vars[fp] = tk.StringVar(value="— select —")
                modify_zalora_vars[fp]   = tk.StringVar(value="")

                tk.Label(row, text="  Marketplace:",
                         font=("Segoe UI", 8), bg=WHITE,
                         fg="#555555").pack(side="left", padx=(10, 0))

                mp_cb = ttk.Combobox(row, textvariable=mod_marketplace_vars[fp],
                                     values=["— select —", "Shopee", "Lazada", "Zalora", "Other"],
                                     state="readonly", width=12,
                                     font=("Segoe UI", 8))
                mp_cb.pack(side="left", padx=(2, 0))

                # Zalora credential widgets — hidden until user picks Zalora
                zal_lbl = tk.Label(row, text="  Zalora Brand:",
                                   font=("Segoe UI", 8), bg=WHITE, fg="#0D4D6A")
                zal_cb  = ttk.Combobox(row, textvariable=modify_zalora_vars[fp],
                                       values=ZALORA_CRED_BRANDS,
                                       state="readonly", width=18,
                                       font=("Segoe UI", 8))

                def _on_mp(event, _fp=fp, _zl=zal_lbl, _zc=zal_cb):
                    if mod_marketplace_vars[_fp].get() == "Zalora":
                        _zl.pack(side="left", padx=(8, 0))
                        _zc.pack(side="left", padx=(2, 0))
                    else:
                        _zl.pack_forget()
                        _zc.pack_forget()
                        modify_zalora_vars[_fp].set("")

                mp_cb.bind("<<ComboboxSelected>>", _on_mp)

            return var

        if channel_map:
            bf = tk.LabelFrame(inner1, text=" Generate For ", bg=WHITE,
                               font=("Segoe UI", 9, "bold"), fg=DARK_BLUE, padx=10, pady=6)
            bf.pack(fill="x", padx=12, pady=(0, 6))

            tk.Label(bf, text="Select which brand/marketplace files to generate output for:",
                     font=("Segoe UI", 8), bg=WHITE, fg="#555555").pack(anchor="w", pady=(0, 4))

            ch_rows = tk.Frame(bf, bg=WHITE)
            ch_rows.pack(fill="x")
            for fp, (brand_name, ch_short) in channel_map.items():
                _make_file_row(ch_rows, fp, brand_name, ch_short, is_modify=False)

            def _brand_all():
                for fp in channel_map: brand_file_vars[fp].set(True)
            def _brand_none():
                for fp in channel_map: brand_file_vars[fp].set(False)

            sc = tk.Frame(bf, bg=WHITE)
            sc.pack(anchor="w", pady=(6, 0))
            tk.Button(sc, text="Select All", font=("Segoe UI", 8), bg="#E8EEF5",
                      relief="flat", padx=8, command=_brand_all).pack(side="left", padx=(0, 4))
            tk.Button(sc, text="Select None", font=("Segoe UI", 8), bg="#E8EEF5",
                      relief="flat", padx=8, command=_brand_none).pack(side="left")



    # Column count badge
    _total_channel = (sum(len(c) for _, _, c in channel_sources)
                      if channel_sources else len(channel_cols))
    total_count = _total_channel + len(ordazzle_cols) + len(sap_cols) + len(modify_cols)
    badge_var   = tk.StringVar()

    def refresh_badge():
        badge_var.set(f"{len(sel_cols)} of {total_count} columns selected")

    hdr_bar = tk.Frame(inner1, bg=DARK_BLUE)
    hdr_bar.pack(fill="x", padx=12, pady=(8, 0))
    tk.Label(hdr_bar, text="Select Output Columns", bg=DARK_BLUE, fg=WHITE,
             font=("Segoe UI", 10, "bold"), padx=8, pady=6).pack(side="left")
    tk.Label(hdr_bar, textvariable=badge_var, bg=ACCENT, fg=DARK_BLUE,
             font=("Segoe UI", 8, "bold"), padx=6, pady=3).pack(side="right", padx=8, pady=6)
    refresh_badge()

    # Per-source column groups
    sources_def = []
    if channel_sources:
        for sk, dl, cols in channel_sources:
            if cols: sources_def.append((sk, cols, dl.split('(')[0].strip()))
    elif channel_files and channel_cols:
        sources_def.append(("channel", channel_cols, "Channel"))
    if ordazzle_files and ordazzle_cols:
        sources_def.append(("ordazzle", ordazzle_cols, "Ordazzle"))
    if sap_files and sap_cols:
        sources_def.append(("sap", sap_cols, "SAP"))
    if modify_cols_per_file:
        for _idx, (_mod_fp, _mod_cols) in enumerate(modify_cols_per_file.items()):
            if _mod_cols:
                _mod_fname  = os.path.basename(_mod_fp)
                _src_key    = f"modify_{_idx}"
                _tile_label = f"Modify — {_mod_fname}"
                sources_def.append((_src_key, _mod_cols, _tile_label))
    elif modify_files_list and modify_cols:
        sources_def.append(("modify", modify_cols, "Modify  ✎"))

    grp_count_vars = {}

    for src, cols, src_label in sources_def:
        grp_cv = tk.StringVar()
        grp_count_vars[src] = grp_cv

        def _refresh_grp(s=src, c=cols, v=grp_cv):
            n = sum(1 for r in sel_cols if r[0] == s)
            v.set(f"{n} of {len(c)} columns")
        _refresh_grp()

        grp_frame = tk.Frame(inner1, bg=WHITE,
                             highlightbackground=BORDER_CLR, highlightthickness=1)
        grp_frame.pack(fill="x", padx=12, pady=(4, 0))
        g_top = tk.Frame(grp_frame, bg=WHITE)
        g_top.pack(fill="x")

        def make_toggle(s=src, c=cols):
            def _toggle():
                all_on = all(any(r[0] == s and r[1] == col for r in sel_cols) for col in c)
                for col in c:
                    v = check_vars.get((s, col))
                    if all_on:
                        sel_cols[:] = [r for r in sel_cols if not (r[0] == s and r[1] == col)]
                        if v: v.set(False)
                    else:
                        if not any(r[0] == s and r[1] == col for r in sel_cols):
                            sel_cols.append([s, col])
                        if v: v.set(True)
                grp_count_vars[s].set(f"{'0' if all_on else len(c)} of {len(c)} columns")
                refresh_badge()
                refresh_order_list()
            return _toggle

        all_on_now  = all(any(r[0] == src and r[1] == c for r in sel_cols) for c in cols)
        grp_chk_var = tk.BooleanVar(value=all_on_now)
        tk.Checkbutton(g_top, variable=grp_chk_var, command=make_toggle(),
                       bg=WHITE, activebackground=WHITE).pack(side="left", padx=4)
        tk.Label(g_top, text=src_label, font=("Segoe UI", 10, "bold"),
                 bg=WHITE, fg=_src_color(src)).pack(side="left", pady=6)

        mod_names_for_src = modify_by_src.get(src, [])
        if mod_names_for_src:
            badge_text = "✎ " + ", ".join(mod_names_for_src)
            tk.Label(g_top, text=badge_text,
                     font=("Segoe UI", 8, "italic"),
                     bg="#FFF8E7", fg="#8B5E00",
                     padx=5, pady=2, relief="groove").pack(side="left", padx=(8, 0), pady=4)

        tk.Label(g_top, textvariable=grp_cv, bg=ACCENT, fg=DARK_BLUE,
                 font=("Segoe UI", 8, "bold"), padx=6, pady=2).pack(side="right", padx=8)
        tk.Frame(grp_frame, bg=BORDER_CLR, height=1).pack(fill="x")
        grid_f = tk.Frame(grp_frame, bg=GROUP_BG)
        grid_f.pack(fill="x", padx=16, pady=4)

        def make_on_check(s, col, v, all_c=cols):
            def _on():
                if v.get():
                    if not any(r[0] == s and r[1] == col for r in sel_cols):
                        sel_cols.append([s, col])
                else:
                    sel_cols[:] = [r for r in sel_cols if not (r[0] == s and r[1] == col)]
                n = sum(1 for r in sel_cols if r[0] == s)
                grp_count_vars[s].set(f"{n} of {len(all_c)} columns")
                refresh_badge()
                refresh_order_list()
            return _on

        for i, col in enumerate(cols):
            is_on  = any(r[0] == src and r[1] == col for r in sel_cols)
            var    = tk.BooleanVar(value=is_on)
            check_vars[(src, col)] = var
            cell_f = tk.Frame(grid_f, bg=GROUP_BG)
            cell_f.grid(row=i // 3, column=i % 3, sticky="w", padx=4, pady=1)
            tk.Checkbutton(cell_f, variable=var, bg=GROUP_BG, activebackground=GROUP_BG,
                           command=make_on_check(src, col, var)).pack(side="left")
            tk.Label(cell_f, text=col, font=("Segoe UI", 9),
                     bg=GROUP_BG, fg="#333333").pack(side="left")
        for ci in range(3):
            grid_f.columnconfigure(ci, weight=1)

    # Base SKU selector
    _ch_disp_map = {}
    if channel_sources:
        for sk, dl, _ in channel_sources:
            _ch_disp_map[sk] = dl
    else:
        _ch_disp_map["channel"] = "Channel"
    _src_display_names = {**_ch_disp_map, "ordazzle": "Ordazzle", "sap": "SAP", "modify": "Modify"}

    # Build a brand-aware label for the Modify radio option
    if modify_files_list:
        from ..utils import detect_brand_from_filename as _dbff
        _mod_brands = [_dbff(fp) for fp in modify_files_list if _dbff(fp)]
        _mod_brand  = _mod_brands[0] if _mod_brands else None
        modify_radio_label = f"Modify — {_mod_brand}  ✎" if _mod_brand else "Modify  ✎"
    else:
        modify_radio_label = "Modify  ✎"

    if _multi_ch:
        base_section_title = " Base SKU — per Marketplace (rows to iterate) "
    elif suggested_base:
        base_section_title = (
            f" Base SKU  ·  Auto-detected: "
            f"{_src_display_names.get(suggested_base, suggested_base)} (user-modified file) "
        )
    else:
        base_section_title = " Base SKU (rows to iterate) "

    base_f = tk.LabelFrame(inner1, text=base_section_title, bg=WHITE,
                            font=("Segoe UI", 9, "bold"), fg=DARK_BLUE, padx=10, pady=6)
    base_f.pack(fill="x", padx=12, pady=(10, 6))

    if suggested_base:
        tk.Label(base_f,
                 text="Modify file detected. Base SKU is set to Modify — change below if needed.",
                 bg="#FFF8E7", fg="#7B4F00", font=("Segoe UI", 8, "italic"),
                 wraplength=520, justify="left", relief="flat", padx=6, pady=4).pack(fill="x", pady=(0, 4))

    if _multi_ch:
        tk.Label(base_f,
                 text="Each marketplace uses its own Base SKU.",
                 bg="#EEF4FB", fg="#1A2A4A", font=("Segoe UI", 8, "italic"),
                 wraplength=520, justify="left", padx=6, pady=3).pack(fill="x", pady=(0, 6))

        for sk, dl, cols in channel_sources:
            if not cols:
                continue
            dl_clean = dl.split("(")[0].strip()   # drop filename suffix from label
            var = base_vars[sk]
            mkt_frame = tk.LabelFrame(
                base_f, text=f" {dl_clean} ",
                bg=WHITE, font=("Segoe UI", 9, "bold"),
                fg=SRC_COLORS.get(sk, DARK_BLUE), padx=8, pady=4,
            )
            mkt_frame.pack(fill="x", pady=(0, 6))

            # This marketplace's channel source first
            tk.Radiobutton(
                mkt_frame, text=dl_clean + "  ← this marketplace",
                variable=var, value=sk,
                bg=WHITE, activebackground=WHITE,
                font=("Segoe UI", 9, "bold"),
                fg=SRC_COLORS.get(sk, DARK_BLUE),
            ).pack(anchor="w")

            # Shared sources
            shared_opts = []
            if ordazzle_files:    shared_opts.append(("ordazzle", "Ordazzle"))
            if sap_files:         shared_opts.append(("sap",      "SAP"))
            if modify_files_list: shared_opts.append(("modify",   modify_radio_label))
            for val, lbl in shared_opts:
                auto_tag = "  (auto)" if val == suggested_base else ""
                row = tk.Frame(mkt_frame, bg=WHITE)
                row.pack(anchor="w", fill="x")
                tk.Radiobutton(
                    row, text=lbl + auto_tag,
                    variable=var, value=val,
                    bg=WHITE, activebackground=WHITE,
                    font=("Segoe UI", 9, "bold" if val == suggested_base else "normal"),
                    fg=SRC_COLORS.get(val, DARK_BLUE) if val == suggested_base else "#333333",
                ).pack(side="left")
                if val == "modify" and len(modify_files_list) > 1:
                    mod_names = [os.path.basename(fp) for fp in modify_files_list]
                    mod_dd_var = tk.StringVar(value=mod_names[0])
                    tk.OptionMenu(row, mod_dd_var, *mod_names).pack(side="left", padx=(6, 0))
    else:
        base_opts = []
        if channel_sources:
            for sk, dl, cols in channel_sources:
                if cols: base_opts.append((sk, dl))
        elif channel_files:
            base_opts.append(("channel", "Channel"))
        if ordazzle_files:    base_opts.append(("ordazzle", "Ordazzle"))
        if sap_files:         base_opts.append(("sap",      "SAP"))
        if modify_files_list: base_opts.append(("modify",   modify_radio_label))
        for val, lbl in base_opts:
            auto_tag = "  (auto)" if val == suggested_base else ""
            row = tk.Frame(base_f, bg=WHITE)
            row.pack(anchor="w", fill="x")
            tk.Radiobutton(row, text=lbl + auto_tag, variable=base_var, value=val,
                           bg=WHITE, activebackground=WHITE,
                           font=("Segoe UI", 9, "bold" if val == suggested_base else "normal"),
                           fg=SRC_COLORS.get(val, DARK_BLUE) if val == suggested_base else "#333333"
                           ).pack(side="left")
            if val == "modify" and len(modify_files_list) > 1:
                mod_names = [os.path.basename(fp) for fp in modify_files_list]
                mod_dd_var = tk.StringVar(value=mod_names[0])
                tk.OptionMenu(row, mod_dd_var, *mod_names).pack(side="left", padx=(6, 0))

    # Column order strip
    order_strip = tk.Frame(tab1, bg=WHITE, highlightbackground=BORDER_CLR, highlightthickness=1)
    order_strip.pack(fill="x", side="bottom")
    tk.Frame(order_strip, bg="#EEEEEE").pack(fill="x")
    hdr_strip = tk.Frame(order_strip, bg="#EEEEEE")
    hdr_strip.pack(fill="x")
    tk.Label(hdr_strip, text="Column Order", bg="#EEEEEE", fg=DARK_BLUE,
             font=("Segoe UI", 9, "bold"), padx=10, pady=5).pack(side="left")
    tk.Label(hdr_strip, text="(↑↓ to reorder, ✕ to remove)",
             bg="#EEEEEE", fg="#666666", font=("Segoe UI", 8)).pack(side="left")

    list_row = tk.Frame(order_strip, bg=WHITE)
    list_row.pack(fill="x", padx=10, pady=6)
    order_lb = tk.Listbox(list_row, height=5, selectmode="single",
                          font=("Segoe UI", 9), relief="solid",
                          highlightthickness=0, borderwidth=1,
                          bg=WHITE, fg=DARK_BLUE,
                          selectbackground=MID_BLUE, selectforeground=WHITE)
    order_lb.pack(side="left", fill="both", expand=True)

    btn_f = tk.Frame(list_row, bg=WHITE)
    btn_f.pack(side="left", padx=4)

    def refresh_order_list():
        cur = order_lb.curselection()
        order_lb.delete(0, "end")
        for i, (src, col_name) in enumerate(sel_cols):
            abbr = {
                "channel": "CH", "channel_shopee": "CH·SP",
                "channel_lazada": "CH·LZ", "channel_zalora": "CH·ZL",
                "ordazzle": "ORD", "sap": "SAP", "modify": "MOD",
            }.get(src, src)
            order_lb.insert("end", f"  {i+1}. [{abbr}] {col_name}")
        if cur:
            try: order_lb.selection_set(cur[0])
            except Exception: pass

    def move_up_col():
        idx = order_lb.curselection()
        if not idx or idx[0] == 0: return
        i = idx[0]
        sel_cols[i-1], sel_cols[i] = sel_cols[i], sel_cols[i-1]
        refresh_order_list()
        order_lb.selection_set(i-1)

    def move_down_col():
        idx = order_lb.curselection()
        if not idx or idx[0] >= len(sel_cols) - 1: return
        i = idx[0]
        sel_cols[i+1], sel_cols[i] = sel_cols[i], sel_cols[i+1]
        refresh_order_list()
        order_lb.selection_set(i+1)

    _src_col_map = {
        "channel": channel_cols, "ordazzle": ordazzle_cols,
        "sap": sap_cols,         "modify": modify_cols,
    }

    def remove_sel_col():
        idx = order_lb.curselection()
        if not idx: return
        i = idx[0]
        src, col_name = sel_cols.pop(i)
        v = check_vars.get((src, col_name))
        if v: v.set(False)
        n = sum(1 for r in sel_cols if r[0] == src)
        if src in grp_count_vars:
            all_c = _src_col_map.get(src, [])
            grp_count_vars[src].set(f"{n} of {len(all_c)} columns")
        refresh_badge()
        refresh_order_list()

    tk.Button(btn_f, text="↑  Up",     width=9, command=move_up_col,
              bg=LIGHT_GRAY, relief="flat", font=("Segoe UI", 9)).pack(pady=2)
    tk.Button(btn_f, text="↓  Down",   width=9, command=move_down_col,
              bg=LIGHT_GRAY, relief="flat", font=("Segoe UI", 9)).pack(pady=2)
    tk.Button(btn_f, text="✕  Remove", width=9, command=remove_sel_col,
              bg="#FFC7CE", relief="flat", font=("Segoe UI", 9)).pack(pady=2)
    refresh_order_list()

    # TAB 2 – Comparisons
    tab2 = tk.Frame(nb, bg="#F4F4F4")
    nb.add(tab2, text="  Comparisons  ")

    # TAB 3 – Config
    import pathlib as _pl
    from .config_tab import build_config_tab as _build_cfg_tab
    _build_cfg_tab(nb, _pl.Path(__file__).parent.parent / "config.py")

    cmp_hdr = tk.Frame(tab2, bg=DARK_BLUE)
    cmp_hdr.pack(fill="x")
    tk.Label(cmp_hdr, text="Define Comparisons",
             bg=DARK_BLUE, fg=WHITE, font=("Segoe UI", 10, "bold"),
             padx=12, pady=8).pack(side="left")
    tk.Label(cmp_hdr,
             text="Compare any two columns from any source  →  TRUE / FALSE / N/A",
             bg=DARK_BLUE, fg="#99AACC", font=("Segoe UI", 9), padx=4).pack(side="left")

    add_f = tk.LabelFrame(tab2, text=" Add a Comparison ", bg=WHITE,
                          font=("Segoe UI", 9, "bold"), fg=DARK_BLUE, padx=10, pady=8)
    add_f.pack(fill="x", padx=12, pady=(10, 4))

    left_var_cmp  = tk.StringVar(value=all_src_labels[0] if all_src_labels else "")
    right_var_cmp = tk.StringVar(value=all_src_labels[1] if len(all_src_labels) > 1 else "")
    lbl_var_cmp   = tk.StringVar(value="")

    for label_text, var in [("Left column:", left_var_cmp), ("Right column:", right_var_cmp)]:
        r = tk.Frame(add_f, bg=WHITE)
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label_text, width=14, anchor="w",
                 font=("Segoe UI", 9), bg=WHITE).pack(side="left")
        ttk.Combobox(r, textvariable=var, values=all_src_labels,
                     state="readonly", width=50).pack(side="left", padx=4)

    r3 = tk.Frame(add_f, bg=WHITE)
    r3.pack(fill="x", pady=2)
    tk.Label(r3, text="Label (optional):", width=14, anchor="w",
             font=("Segoe UI", 9), bg=WHITE).pack(side="left")
    tk.Entry(r3, textvariable=lbl_var_cmp, width=52,
             font=("Segoe UI", 9), relief="solid", borderwidth=1).pack(side="left", padx=4)

    cmp_display = tk.Frame(tab2, bg=WHITE,
                           highlightbackground=BORDER_CLR, highlightthickness=1)
    cmp_display.pack(fill="both", expand=True, padx=12, pady=(4, 4))
    cmp_hdr2 = tk.Frame(cmp_display, bg="#EEEEEE")
    cmp_hdr2.pack(fill="x")
    for txt, w in [("Left Column", 28), ("Right Column", 28), ("Output Label", 25), ("", 6)]:
        tk.Label(cmp_hdr2, text=txt, width=w, anchor="w",
                 font=("Segoe UI", 9, "bold"), bg="#EEEEEE",
                 fg=DARK_BLUE, padx=6, pady=4).pack(side="left")

    cmp_rows_f = tk.Frame(cmp_display, bg=WHITE)
    cmp_rows_f.pack(fill="both", expand=True)

    def refresh_cmp_display():
        for w in cmp_rows_f.winfo_children(): w.destroy()
        for i, (lsrc, lcol, rsrc, rcol, lbl) in enumerate(cmp_list):
            bg = "#F5F5F5" if i % 2 == 0 else WHITE
            rf = tk.Frame(cmp_rows_f, bg=bg)
            rf.pack(fill="x")
            tk.Label(rf, text=fmt_src_col(lsrc, lcol), width=28, anchor="w",
                     font=("Segoe UI", 9), bg=bg, padx=6, pady=3).pack(side="left")
            tk.Label(rf, text=fmt_src_col(rsrc, rcol), width=28, anchor="w",
                     font=("Segoe UI", 9), bg=bg, padx=6).pack(side="left")
            tk.Label(rf, text=lbl, width=25, anchor="w",
                     font=("Segoe UI", 9, "bold"), bg=bg,
                     fg=MID_BLUE, padx=6).pack(side="left")
            tk.Button(rf, text="✕", bg="#FFC7CE", fg="#333333",
                      font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                      command=lambda idx=i: (_del_cmp(idx))).pack(side="left", padx=4)

    def _del_cmp(idx):
        cmp_list.pop(idx)
        refresh_cmp_display()

    def add_cmp():
        lv, rv = left_var_cmp.get(), right_var_cmp.get()
        if not lv or not rv: return
        if lv not in all_src_labels or rv not in all_src_labels: return
        lsrc, lcol = all_src_cols[all_src_labels.index(lv)]
        rsrc, rcol = all_src_cols[all_src_labels.index(rv)]
        lbl = lbl_var_cmp.get().strip()
        if not lbl:
            lbl = f"{fmt_src_col(lsrc, lcol)} × {fmt_src_col(rsrc, rcol)}"
        cmp_list.append([lsrc, lcol, rsrc, rcol, lbl])
        lbl_var_cmp.set("")
        refresh_cmp_display()

    tk.Button(add_f, text="+ Add Comparison", command=add_cmp,
              bg=MID_BLUE, fg=WHITE, font=("Segoe UI", 9, "bold"),
              relief="flat", cursor="hand2", padx=10).pack(side="right", pady=4)

    def _add_defaults():
        ord_pub = next((c for c in ordazzle_cols if "PUBLISHED" in c.upper()), None)
        sap_unr = next((c for c in sap_cols    if "UNRESTRICTED" in c.upper()), None)
        buf_stk = next((c for c in ordazzle_cols if "BUFFER" in c.upper()), None)
        defaults = []
        if ord_pub and sap_unr:
            defaults.append(["ordazzle", ord_pub, "sap", sap_unr, "Ordazzle × SAP"])
        if buf_stk and sap_unr:
            defaults.append(["ordazzle", buf_stk, "sap", sap_unr, "Buffer × SAP"])
        ch_sources = channel_sources if channel_sources else [("channel", "Channel", channel_cols)]
        for sk, dl, cols in ch_sources:
            ch_stk = next((c for c in cols if c.lower() in ("stock", "quantity")), None)
            short  = dl.replace("Channel — ", "").replace("Channel", "CH")
            if ord_pub and ch_stk:
                defaults.append(["ordazzle", ord_pub, sk, ch_stk, f"Ordazzle × {short}"])
            if buf_stk and ch_stk:
                defaults.append(["ordazzle", buf_stk, sk, ch_stk, f"Buffer × {short}"])
            if ch_stk and sap_unr:
                defaults.append([sk, ch_stk, "sap", sap_unr, f"{short} × SAP"])
        cmp_list.extend(defaults)

    refresh_cmp_display()
    _deferred_cmp_refresh.append(refresh_cmp_display)

    # Run / Cancel bar
    btn_bar = tk.Frame(root, bg="#F4F4F4")
    btn_bar.pack(fill="x", padx=14, pady=(4, 10), side="bottom")

    def on_run():
        import tkinter.messagebox as mb
        if not sel_cols and not cmp_list:
            mb.showwarning("Nothing selected",
                           "Select at least one output column or comparison.")
            return
        # Brand filter validation
        if brand_file_vars:
            chosen = [fp for fp, v in brand_file_vars.items() if v.get()]
            if not chosen:
                mb.showwarning("No Brand Selected",
                               "Please select at least one brand/marketplace to generate.")
                return
            result["selected_files"] = chosen
        else:
            result["selected_files"] = None

        def _norm_src(src):
            return "modify" if src.startswith("modify_") else src

        result["output_cols"] = [(_norm_src(r[0]), r[1]) for r in sel_cols]
        result["comparisons"] = [tuple(r) for r in cmp_list]
        if _multi_ch:
            result["base"] = {k: v.get() for k, v in base_vars.items()}
        else:
            result["base"] = base_var.get()
        # Zalora options — brand chosen inline per row; selecting any brand = extract MPID
        result["zalora_options"] = {
            "extract_mpid":    True,
            "extract_mpskuid": True,
            "zalora_file_brands": {
                fp: v.get() for fp, v in zalora_file_vars.items() if v.get()
            },
            "modify_zalora_brands": {
                fp: v.get() for fp, v in modify_zalora_vars.items()
                if v.get() and v.get() not in ("", "None")
            },
            "modify_marketplaces": {
                fp: v.get() for fp, v in mod_marketplace_vars.items()
                if v.get() not in ("— select —", "")
            },
        }
        root.destroy()

    def on_cancel():
        root.destroy()

    tk.Button(btn_bar, text="Run", width=12, command=on_run,
              bg=MID_BLUE, fg=WHITE, font=("Segoe UI", 10, "bold"),
              relief="flat", cursor="hand2").pack(side="right", padx=(6, 0))
    tk.Button(btn_bar, text="Cancel", width=10, command=on_cancel,
              bg=LIGHT_GRAY, relief="flat", font=("Segoe UI", 9)).pack(side="right")

    # Center window
    root.update_idletasks()
    w = min(root.winfo_reqwidth(), root.winfo_screenwidth() - 40)
    h = min(860, root.winfo_screenheight() - 60)
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()

    if result["output_cols"] is None:
        return None, None, None, None, None
    return (result["output_cols"], result["comparisons"], result["base"],
            result["selected_files"], result.get("zalora_options", {}))