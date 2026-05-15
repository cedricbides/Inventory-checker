"""
config_tab.py  —  GUI tab for editing config.py
================================================
Place in  inventory_pkg/gui/config_tab.py

Integration — add these 3 lines inside launch_gui() in app.py,
right after:  nb.add(tab2, text="  Comparisons  ")

    import pathlib as _pl
    from .config_tab import build_config_tab as _build_cfg_tab
    _build_cfg_tab(nb, _pl.Path(__file__).parent.parent / "config.py")
"""

import pathlib
import pprint
import importlib.util


# colours (match app.py)
DARK_BLUE  = "#1A2A4A"
MID_BLUE   = "#2E4A7A"
WHITE      = "#FFFFFF"
GROUP_BG   = "#FAFAFA"
RED_LIGHT  = "#FFC7CE"
SHOPEE_CLR = "#EE4D2D"   # Shopee orange-red
LAZADA_CLR = "#0F146D"   # Lazada deep blue
ZALORA_CLR = "#1A2A4A"   # match dark blue


def _load_config(config_path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("_inv_cfg_live", config_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _save_config(config_path: pathlib.Path, data: dict):
    pp = lambda v: pprint.pformat(v, indent=4, width=88)
    text = f'''\
"""
config.py  —  ALL User Settings
================================
This is the ONLY file you need to edit.
No other files need to be touched.

SECTIONS
--------
  1. BRAND GROUPS       — brands, warehouse, SAP site, storage location
  2. BRAND ALIASES      — alternate spellings that map to a canonical brand name
  3. CHANNEL API CREDENTIALS
       3a. SHOPEE       — Shop ID, Partner ID, Partner Key per brand
       3b. LAZADA       — App Key, App Secret, Access Token per brand
       3c. ZALORA       — Client ID, Client Secret per brand
  4. FOLDERS            — subfolder names created in the working directory
  5. FILE PATTERNS      — how the tool detects which file belongs to which source
  6. OUTPUT SETTINGS    — result filename prefix and timestamp format
  7. APP SETTINGS       — UI mode, default base SKU source
  8. QUICK EXPORT       — which columns are auto-selected by Quick Export (TUI)
"""



# 1. BRAND GROUPS


BRAND_GROUPS = {pp(data["brand_groups"])}



# 2. BRAND ALIASES


BRAND_ALIASES = {pp(data["brand_aliases"])}



# 3a. SHOPEE API CREDENTIALS
#     Shopee Open Platform  →  Seller Center → Account → API Credentials
#     Fields: shop_id, partner_id, partner_key


SHOPEE_CREDENTIALS = {pp(data["shopee_creds"])}



# 3b. LAZADA API CREDENTIALS
#     Lazada Open Platform  →  Developer Center → My Apps
#     Fields: app_key, app_secret, access_token


LAZADA_CREDENTIALS = {pp(data["lazada_creds"])}



# 3c. ZALORA API CREDENTIALS
#     Zalora Seller Center → Settings → API Keys
#     Fields: client_id, client_secret


ZALORA_CREDENTIALS = {pp(data["zalora_creds"])}



# 4. FOLDERS


FOLDERS = {pp(data["folders"])}



# 5. FILE PATTERNS


FILE_PATTERNS = {pp(data["file_patterns"])}



# 6. OUTPUT SETTINGS


OUTPUT = {pp(data["output"])}



# 7. APP SETTINGS


APP = {pp(data["app"])}



# 8. QUICK EXPORT COLUMNS  (TUI — terminal mode only)


QUICK_EXPORT_COLUMNS = {pp(data["quick_export"])}
'''
    config_path.write_text(text, encoding="utf-8")


def build_config_tab(nb, config_path: pathlib.Path):
    """Add '⚙ Config' tab to *nb* (ttk.Notebook that already lives in root)."""
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        return

    cfg = _load_config(config_path)

    # working copies
    brand_groups  = [dict(g, brands=list(g["brands"])) for g in cfg.BRAND_GROUPS]
    brand_aliases = dict(cfg.BRAND_ALIASES)
    shopee_creds  = {k: dict(v) for k, v in
                     getattr(cfg, "SHOPEE_CREDENTIALS", {}).items()}
    lazada_creds  = {k: dict(v) for k, v in
                     getattr(cfg, "LAZADA_CREDENTIALS", {}).items()}
    zalora_creds  = {k: dict(v) for k, v in cfg.ZALORA_CREDENTIALS.items()}
    folders       = dict(cfg.FOLDERS)
    file_patterns = {k: list(v) for k, v in cfg.FILE_PATTERNS.items()}
    output_cfg    = dict(cfg.OUTPUT)
    app_cfg       = dict(cfg.APP)
    quick_export  = {k: (src, list(cols))
                     for k, (src, cols) in cfg.QUICK_EXPORT_COLUMNS.items()}

    # ── outer tab ─────────────────────────────────────────────────────────────
    outer = tk.Frame(nb, bg="#F4F4F4")
    nb.add(outer, text="  \u2699 Config  ")

    hdr = tk.Frame(outer, bg=DARK_BLUE)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Configuration", bg=DARK_BLUE, fg=WHITE,
             font=("Segoe UI", 10, "bold"), padx=12, pady=8).pack(side="left")
    tk.Label(hdr, text="Edit and save all settings from config.py",
             bg=DARK_BLUE, fg="#99AACC", font=("Segoe UI", 9), padx=4).pack(side="left")

    # save bar 
    save_bar   = tk.Frame(outer, bg="#F4F4F4")
    save_bar.pack(fill="x", padx=8, pady=(4, 8), side="bottom")
    status_var = tk.StringVar(value="")
    tk.Label(save_bar, textvariable=status_var, bg="#F4F4F4",
             font=("Segoe UI", 9), fg="#2A6A4A").pack(side="left")

    collectors = []

    def save_all():
        try:
            for fn in collectors:
                fn()
            _save_config(config_path, {
                "brand_groups":  brand_groups,
                "brand_aliases": brand_aliases,
                "shopee_creds":  shopee_creds,
                "lazada_creds":  lazada_creds,
                "zalora_creds":  zalora_creds,
                "folders":       folders,
                "file_patterns": file_patterns,
                "output":        output_cfg,
                "app":           app_cfg,
                "quick_export":  quick_export,
            })
            status_var.set("\u2714  config.py saved")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            status_var.set("")

    tk.Button(save_bar, text="\U0001f4be  Save Config", command=save_all,
              bg=MID_BLUE, fg=WHITE, font=("Segoe UI", 9, "bold"),
              relief="flat", cursor="hand2", padx=14, pady=3).pack(side="right")

    # sub-notebook 
    sub = ttk.Notebook(outer)
    sub.pack(fill="both", expand=True, padx=8, pady=(6, 0))

    
    # helper: scrollable cred table used by all three API sections
    
    def _make_cred_table(parent, store: dict, columns: list):
        """
        Build a scrollable rows-of-Entry table inside *parent*.
        columns: list of (display_label, dict_key, entry_width)
        Returns a collect() function that writes back to *store*.
        """
        hf = tk.Frame(parent, bg="#EEEEEE")
        hf.pack(fill="x", padx=0, pady=(0, 2))
        for col_label, _, col_width in columns:
            tk.Label(hf, text=col_label, width=col_width, anchor="w",
                     font=("Segoe UI", 9, "bold"), bg="#EEEEEE",
                     fg=DARK_BLUE, padx=4, pady=3).pack(side="left")

        canvas = tk.Canvas(parent, bg=WHITE, highlightthickness=0, height=180)
        vsb    = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=WHITE)
        wid   = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        rows = []   # list of (brand_var, {key: StringVar}, row_frame)

        def add_row(brand="", vals=None):
            vals = vals or {}
            row  = tk.Frame(inner, bg=WHITE)
            row.pack(fill="x", padx=4, pady=1)

            brand_var = tk.StringVar(value=brand)
            tk.Entry(row, textvariable=brand_var, font=("Segoe UI", 9),
                     relief="solid", bd=1,
                     width=columns[0][2]).pack(side="left", padx=(0, 3))

            field_vars = {}
            for _, fkey, fwidth in columns[1:]:
                fvar = tk.StringVar(value=vals.get(fkey, ""))
                tk.Entry(row, textvariable=fvar, font=("Segoe UI", 9),
                         relief="solid", bd=1,
                         width=fwidth).pack(side="left", padx=(0, 3))
                field_vars[fkey] = fvar

            def _del():
                rows.remove((brand_var, field_vars, row))
                row.destroy()
            tk.Button(row, text="\u2715", command=_del, bg=RED_LIGHT,
                      font=("Segoe UI", 8, "bold"), relief="flat",
                      cursor="hand2", width=2).pack(side="left")
            rows.append((brand_var, field_vars, row))

        for brand, creds in sorted(store.items()):
            add_row(brand, creds)

        btn_bar = tk.Frame(parent, bg=WHITE)
        btn_bar.pack(fill="x", pady=(4, 0))
        tk.Button(btn_bar, text="+ Add Brand", command=add_row,
                  bg=MID_BLUE, fg=WHITE, font=("Segoe UI", 8, "bold"),
                  relief="flat", cursor="hand2").pack(side="left")

        def collect():
            store.clear()
            for brand_var, field_vars, _ in rows:
                b = brand_var.get().strip()
                if b:
                    store[b] = {k: v.get().strip() for k, v in field_vars.items()}

        return collect

    
    # TAB A BRAND GROUPS
    
    def _tab_brand_groups():
        f = tk.Frame(sub, bg=WHITE)
        sub.add(f, text=" Brand Groups ")

        left = tk.Frame(f, bg=WHITE, width=175)
        left.pack(side="left", fill="y", padx=(8, 0), pady=8)
        left.pack_propagate(False)
        tk.Label(left, text="Groups", font=("Segoe UI", 9, "bold"),
                 bg=WHITE, fg=DARK_BLUE).pack(anchor="w")
        lb = tk.Listbox(left, font=("Segoe UI", 9), selectbackground=MID_BLUE,
                        selectforeground=WHITE, relief="solid", bd=1,
                        highlightthickness=0, activestyle="none")
        lb.pack(fill="both", expand=True)
        btn_row = tk.Frame(left, bg=WHITE)
        btn_row.pack(fill="x", pady=(4, 0))

        right = tk.Frame(f, bg=GROUP_BG, relief="solid", bd=1)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        dw  = {}
        cur = [None]

        def refresh_lb():
            lb.delete(0, "end")
            for g in brand_groups:
                lb.insert("end", g["group"])

        def load_detail(i):
            g = brand_groups[i]
            dw["grp"].set(g["group"])
            dw["wh"].set(g["warehouse"])
            dw["site"].set(g["sap_site"])
            dw["sloc"].set(g["storage_loc"])
            dw["brands"].delete("1.0", "end")
            dw["brands"].insert("1.0", "\n".join(g["brands"]))

        def flush_detail(i):
            g = brand_groups[i]
            g["group"]       = dw["grp"].get().strip()
            g["warehouse"]   = dw["wh"].get().strip()
            g["sap_site"]    = dw["site"].get().strip()
            g["storage_loc"] = dw["sloc"].get().strip()
            raw = dw["brands"].get("1.0", "end").strip()
            g["brands"] = [b.strip() for b in raw.splitlines() if b.strip()]

        def on_select(evt=None):
            sel = lb.curselection()
            if not sel:
                return
            if cur[0] is not None:
                flush_detail(cur[0])
            cur[0] = sel[0]
            load_detail(sel[0])
            refresh_lb()
            lb.selection_set(sel[0])

        lb.bind("<<ListboxSelect>>", on_select)

        def add_group():
            if cur[0] is not None:
                flush_detail(cur[0])
            brand_groups.append({"group": "NEW_GROUP", "brands": [],
                                  "warehouse": "", "sap_site": "", "storage_loc": "0002"})
            refresh_lb()
            i = len(brand_groups) - 1
            lb.selection_clear(0, "end")
            lb.selection_set(i)
            lb.see(i)
            cur[0] = i
            load_detail(i)

        def del_group():
            if cur[0] is None:
                return
            i = cur[0]
            brand_groups.pop(i)
            cur[0] = None
            refresh_lb()
            if brand_groups:
                ni = min(i, len(brand_groups) - 1)
                lb.selection_set(ni)
                cur[0] = ni
                load_detail(ni)

        tk.Button(btn_row, text="+ Add", command=add_group,
                  bg=MID_BLUE, fg=WHITE, font=("Segoe UI", 8, "bold"),
                  relief="flat", cursor="hand2").pack(side="left", padx=(0, 4))
        tk.Button(btn_row, text="\u2715 Del", command=del_group,
                  bg=RED_LIGHT, font=("Segoe UI", 8, "bold"),
                  relief="flat", cursor="hand2").pack(side="left")

        for label, key in [("Group name", "grp"), ("Warehouse", "wh"),
                            ("SAP site",   "site"), ("Storage loc", "sloc")]:
            row = tk.Frame(right, bg=GROUP_BG)
            row.pack(fill="x", padx=10, pady=(8 if key == "grp" else 3, 0))
            tk.Label(row, text=label, width=12, anchor="w",
                     font=("Segoe UI", 9), bg=GROUP_BG, fg=DARK_BLUE).pack(side="left")
            var = tk.StringVar()
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     relief="solid", bd=1, width=38).pack(side="left", padx=4)
            dw[key] = var

        tk.Label(right, text="Brands  (one per line)", font=("Segoe UI", 9),
                 bg=GROUP_BG, fg=DARK_BLUE, anchor="w").pack(
                     fill="x", padx=10, pady=(10, 2))
        txt = tk.Text(right, font=("Segoe UI", 9), relief="solid", bd=1,
                      height=10, wrap="word")
        txt.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        dw["brands"] = txt

        refresh_lb()
        if brand_groups:
            lb.selection_set(0)
            cur[0] = 0
            load_detail(0)

        collectors.append(lambda: flush_detail(cur[0]) if cur[0] is not None else None)

    _tab_brand_groups()

    
    # TAB B BRAND ALIASES
    
    def _tab_aliases():
        f = tk.Frame(sub, bg=WHITE)
        sub.add(f, text=" Aliases ")
        tk.Label(f, text="Alias (lowercase)  \u2192  Canonical Brand Name",
                 font=("Segoe UI", 9), bg=WHITE, fg="#555", padx=10, pady=6).pack(anchor="w")

        canvas = tk.Canvas(f, bg=WHITE, highlightthickness=0)
        vsb    = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=WHITE)
        wid   = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        rows = []

        def add_row(alias="", canonical=""):
            row = tk.Frame(inner, bg=WHITE)
            row.pack(fill="x", padx=8, pady=1)
            av = tk.StringVar(value=alias)
            cv = tk.StringVar(value=canonical)
            tk.Entry(row, textvariable=av, font=("Segoe UI", 9),
                     relief="solid", bd=1, width=26).pack(side="left", padx=(0, 4))
            tk.Label(row, text="\u2192", font=("Segoe UI", 9),
                     bg=WHITE, fg="#888").pack(side="left")
            tk.Entry(row, textvariable=cv, font=("Segoe UI", 9),
                     relief="solid", bd=1, width=26).pack(side="left", padx=4)

            def _del():
                rows.remove((av, cv, row))
                row.destroy()
            tk.Button(row, text="\u2715", command=_del, bg=RED_LIGHT,
                      font=("Segoe UI", 8, "bold"), relief="flat",
                      cursor="hand2", width=2).pack(side="left", padx=2)
            rows.append((av, cv, row))

        for a, c in sorted(brand_aliases.items()):
            add_row(a, c)

        btn_bar = tk.Frame(f, bg=WHITE)
        btn_bar.pack(fill="x", padx=8, pady=4, side="bottom")
        tk.Button(btn_bar, text="+ Add Alias", command=add_row,
                  bg=MID_BLUE, fg=WHITE, font=("Segoe UI", 9, "bold"),
                  relief="flat", cursor="hand2").pack(side="left")

        def collect():
            brand_aliases.clear()
            for av, cv, _ in rows:
                a = av.get().strip().lower()
                c = cv.get().strip()
                if a and c:
                    brand_aliases[a] = c
        collectors.append(collect)

    _tab_aliases()

    
    # TAB C — CHANNEL APIs  (Shopee + Lazada + Zalora in one scrollable tab)
    
    def _tab_channel_apis():
        outer_f = tk.Frame(sub, bg=WHITE)
        sub.add(outer_f, text=" Channel APIs ")

        # make the whole tab scrollable so all three sections are reachable
        canvas = tk.Canvas(outer_f, bg=WHITE, highlightthickness=0)
        vsb    = ttk.Scrollbar(outer_f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        scroll_f = tk.Frame(canvas, bg=WHITE)
        wid      = canvas.create_window((0, 0), window=scroll_f, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        scroll_f.bind("<Configure>",
                      lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # SHOPEE 
        sp_frame = tk.LabelFrame(
            scroll_f,
            text="  \U0001f6d2  Shopee API Credentials",
            font=("Segoe UI", 9, "bold"), fg=SHOPEE_CLR,
            bg=WHITE, padx=8, pady=6,
        )
        sp_frame.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(sp_frame,
                 text="Shopee Open Platform  \u2192  Seller Center \u2192 Account \u2192 API Credentials",
                 font=("Segoe UI", 8), bg=WHITE, fg="#888").pack(anchor="w", pady=(0, 4))

        sp_cols = [
            ("Brand",       "brand",       14),
            ("Shop ID",     "shop_id",     14),
            ("Partner ID",  "partner_id",  14),
            ("Partner Key", "partner_key", 36),
        ]
        sp_collect = _make_cred_table(sp_frame, shopee_creds, sp_cols)

        #  LAZADA 
        lz_frame = tk.LabelFrame(
            scroll_f,
            text="  \U0001f6cd  Lazada API Credentials",
            font=("Segoe UI", 9, "bold"), fg=LAZADA_CLR,
            bg=WHITE, padx=8, pady=6,
        )
        lz_frame.pack(fill="x", padx=10, pady=6)

        tk.Label(lz_frame,
                 text="Lazada Open Platform  \u2192  Developer Center \u2192 My Apps",
                 font=("Segoe UI", 8), bg=WHITE, fg="#888").pack(anchor="w", pady=(0, 4))

        lz_cols = [
            ("Brand",        "brand",        14),
            ("App Key",      "app_key",      18),
            ("App Secret",   "app_secret",   28),
            ("Access Token", "access_token", 22),
        ]
        lz_collect = _make_cred_table(lz_frame, lazada_creds, lz_cols)

        # ZALORA
        zl_frame = tk.LabelFrame(
            scroll_f,
            text="  \U0001f4b3  Zalora API Credentials",
            font=("Segoe UI", 9, "bold"), fg=ZALORA_CLR,
            bg=WHITE, padx=8, pady=6,
        )
        zl_frame.pack(fill="x", padx=10, pady=(6, 10))

        tk.Label(zl_frame,
                 text="Zalora Seller Center  \u2192  Settings \u2192 API Keys",
                 font=("Segoe UI", 8), bg=WHITE, fg="#888").pack(anchor="w", pady=(0, 4))

        zl_cols = [
            ("Brand",         "brand",         16),
            ("Client ID",     "client_id",     24),
            ("Client Secret", "client_secret", 40),
        ]
        zl_collect = _make_cred_table(zl_frame, zalora_creds, zl_cols)

        def collect():
            sp_collect()
            lz_collect()
            zl_collect()
        collectors.append(collect)

    _tab_channel_apis()

    
    # TAB D — FOLDERS
    
    def _tab_folders():
        f = tk.Frame(sub, bg=WHITE)
        sub.add(f, text=" Folders ")
        tk.Label(f, text="Change the right-hand value to rename the folders the tool creates.",
                 font=("Segoe UI", 9), bg=WHITE, fg="#555", padx=10, pady=8).pack(anchor="w")

        fvars = {}
        for key, val in folders.items():
            row = tk.Frame(f, bg=WHITE)
            row.pack(fill="x", padx=16, pady=3)
            tk.Label(row, text=key, width=12, anchor="w",
                     font=("Segoe UI", 9, "bold"), bg=WHITE, fg=DARK_BLUE).pack(side="left")
            tk.Label(row, text="\u2192", font=("Segoe UI", 9),
                     bg=WHITE, fg="#888").pack(side="left", padx=4)
            var = tk.StringVar(value=val)
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     relief="solid", bd=1, width=24).pack(side="left")
            fvars[key] = var

        def collect():
            for k, v in fvars.items():
                val = v.get().strip()
                if val:
                    folders[k] = val
        collectors.append(collect)

    _tab_folders()

    
    # TAB E — FILE PATTERNS
    
    def _tab_patterns():
        f = tk.Frame(sub, bg=WHITE)
        sub.add(f, text=" File Patterns ")
        tk.Label(f, text="Comma-separated prefixes / keywords (case-insensitive)",
                 font=("Segoe UI", 9), bg=WHITE, fg="#555", padx=10, pady=6).pack(anchor="w")

        pvars = {}
        for key, vals in file_patterns.items():
            row = tk.Frame(f, bg=WHITE)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=key, width=22, anchor="w",
                     font=("Segoe UI", 9, "bold"), bg=WHITE, fg=DARK_BLUE).pack(side="left")
            var = tk.StringVar(value=", ".join(vals))
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     relief="solid", bd=1, width=46).pack(side="left", padx=4)
            pvars[key] = var

        def collect():
            for k, v in pvars.items():
                raw = v.get().strip()
                file_patterns[k] = [p.strip() for p in raw.split(",") if p.strip()]
        collectors.append(collect)

    _tab_patterns()

 
    # TAB F — SETTINGS  (Output + App + Quick Export TUI toggle)

    def _tab_settings():
        f = tk.Frame(sub, bg=WHITE)
        sub.add(f, text=" Settings ")

        sec_out = tk.LabelFrame(f, text=" Output Settings ",
                                font=("Segoe UI", 9, "bold"), fg=DARK_BLUE,
                                bg=WHITE, padx=10, pady=8)
        sec_out.pack(fill="x", padx=12, pady=(14, 6))

        ovars = {}
        for key, label in [("file_prefix",      "File prefix"),
                            ("timestamp_format", "Timestamp format")]:
            row = tk.Frame(sec_out, bg=WHITE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=18, anchor="w",
                     font=("Segoe UI", 9), bg=WHITE, fg=DARK_BLUE).pack(side="left")
            var = tk.StringVar(value=output_cfg.get(key, ""))
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     relief="solid", bd=1, width=36).pack(side="left", padx=4)
            ovars[key] = var
        tk.Label(sec_out,
                 text="Codes: %Y=year  %m=month  %d=day  %H=hour  %M=minute",
                 font=("Segoe UI", 8), bg=WHITE, fg="#888").pack(anchor="w", pady=(4, 0))

        sec_app = tk.LabelFrame(f, text=" App Settings ",
                                font=("Segoe UI", 9, "bold"), fg=DARK_BLUE,
                                bg=WHITE, padx=10, pady=8)
        sec_app.pack(fill="x", padx=12, pady=6)

        use_gui_var = tk.BooleanVar(value=bool(app_cfg.get("use_gui", False)))
        tk.Checkbutton(sec_app,
                       text="use_gui  (open this tkinter window; requires a display)",
                       variable=use_gui_var, bg=WHITE, font=("Segoe UI", 9),
                       fg=DARK_BLUE, activebackground=WHITE).pack(anchor="w")

        r2 = tk.Frame(sec_app, bg=WHITE)
        r2.pack(fill="x", pady=(6, 0))
        tk.Label(r2, text="default_base_sku", width=18, anchor="w",
                 font=("Segoe UI", 9), bg=WHITE, fg=DARK_BLUE).pack(side="left")
        base_var = tk.StringVar(value=app_cfg.get("default_base_sku", "channel"))
        ttk.Combobox(r2, textvariable=base_var,
                     values=["channel", "ordazzle", "sap"],
                     state="readonly", width=14).pack(side="left", padx=4)

        sec_qe = tk.LabelFrame(f, text=" Quick Export  (TUI / terminal mode) ",
                               font=("Segoe UI", 9, "bold"), fg=DARK_BLUE,
                               bg=WHITE, padx=10, pady=8)
        sec_qe.pack(fill="x", padx=12, pady=6)

        qe_var = tk.BooleanVar(value=bool(app_cfg.get("enable_quick_export", True)))
        tk.Checkbutton(sec_qe,
                       text="Enable Quick Export prompt in TUI\n"
                            "    (uncheck to always skip to manual column selection)",
                       variable=qe_var, bg=WHITE, font=("Segoe UI", 9),
                       fg=DARK_BLUE, activebackground=WHITE, justify="left").pack(anchor="w")

        def collect():
            output_cfg["file_prefix"]      = ovars["file_prefix"].get().strip()
            output_cfg["timestamp_format"] = ovars["timestamp_format"].get().strip()
            app_cfg["use_gui"]             = use_gui_var.get()
            app_cfg["default_base_sku"]    = base_var.get()
            app_cfg["enable_quick_export"] = qe_var.get()
        collectors.append(collect)

    _tab_settings()