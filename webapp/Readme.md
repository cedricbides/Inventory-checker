# Inventory Checker — Full Setup Guide

Complete step-by-step instructions for a **brand-new machine** — from zero to running.

---

## What This Project Does

| Tool | Purpose |
|------|---------|
| **Web App** (`app.py`) | Upload channel files, generate & download the inventory Excel report in a browser |
| **Ordazzle Playwright** (`ordazzle_playwright.py`) | Auto-logs into Ordazzle, triggers a warehouse export, waits for the email, and downloads the file |
| **Shopee Playwright** (`shopee_playwright.py`) | Auto-logs into Shopee and downloads inventory data |

---

## Requirements

- **Windows 10 / 11** (the Chrome profile path in Ordazzle is set to a Windows path)
- **Python 3.10 or newer** — download from https://www.python.org/downloads/
  - During install, tick **"Add Python to PATH"** before clicking Install Now
- **Google Chrome** — download from https://www.google.com/chrome/

---

## Step 1 — Get the project folder

If you received a `.zip` file, extract it anywhere (e.g. your Desktop).  
You should end up with a folder called:

```
Inventory checking by python/
```

Open a terminal (Command Prompt or PowerShell) and navigate into it:

```bash
cd "C:\Users\YourName\Desktop\Inventory checking by python"
```

> **Tip:** You can type `cd ` then drag the folder into the terminal window — it pastes the path automatically.

---

## Step 2 — Install Python packages

Run these two commands one after the other:

```bash
pip install -r requirements.txt
pip install -r "web base app/requirements-web.txt"
```

Then install the Playwright browser (one-time only):

```bash
playwright install chromium
```

> If `pip` is not found, try `pip3` instead.  
> If `playwright` is not found, try `python -m playwright install chromium`.

---

## Step 3 — Create your `.env` file

The `.env` file holds all passwords and API keys. **It is never shared or committed to git.**

In the project root folder, create a file called exactly `.env` (no other extension).  
Paste and fill in the values below:

```env
# ── Ordazzle ───────────────────────────────────────────────
ORDAZZLE_USER=your_ordazzle_email@example.com
ORDAZZLE_PASS=your_ordazzle_password

# ── Gmail (used to receive the Ordazzle export email) ──────
GMAIL_USER=your_gmail@gmail.com
GMAIL_PASS=your_gmail_app_password

# ── Shopee ─────────────────────────────────────────────────
SHOPEE_USER=your_shopee_username
SHOPEE_PASS=your_shopee_password

# ── Zalora API keys (one pair per brand) ───────────────────
ZALORA_BANANA_REPUBLIC_ID=
ZALORA_BANANA_REPUBLIC_SECRET=
ZALORA_GAP_ID=
ZALORA_GAP_SECRET=
ZALORA_LACOSTE_ID=
ZALORA_LACOSTE_SECRET=
ZALORA_LUSH_ID=
ZALORA_LUSH_SECRET=
ZALORA_MAKEROOM_ID=
ZALORA_MAKEROOM_SECRET=
ZALORA_OLD_NAVY_ID=
ZALORA_OLD_NAVY_SECRET=
ZALORA_PAYLESS_ID=
ZALORA_PAYLESS_SECRET=
ZALORA_POLO_RALPH_LAUREN_ID=
ZALORA_POLO_RALPH_LAUREN_SECRET=
ZALORA_POMELO_ID=
ZALORA_POMELO_SECRET=
ZALORA_FFS_CSQ_ID=
ZALORA_FFS_CSQ_SECRET=
ZALORA_FFS_ROCKWELL_ID=
ZALORA_FFS_ROCKWELL_SECRET=
ZALORA_FFW_ID=
ZALORA_FFW_SECRET=

# ── Optional ────────────────────────────────────────────────
# How long (in seconds) to wait for the Ordazzle export email.
# Default is 3600 (1 hour). Reduce to 600 (10 min) if your exports are fast.
ORDAZZLE_EMAIL_WAIT_SECONDS=3600
```

> **Gmail App Password vs. regular password**  
> If your Gmail account has 2-Step Verification (recommended), you cannot use your
> normal password here. Go to **Google Account → Security → App passwords**, create
> one for "Mail", and paste that 16-character code as `GMAIL_PASS`.

---

## Step 4 — Run the Ordazzle export script

Open a terminal in the `web base app` folder:

```bash
cd "C:\Users\YourName\Desktop\Inventory checking by python\web base app"
python ordazzle_playwright.py
```

You will see an interactive menu:

```
══════════════════════════════════════════════════════════
  Ordazzle — Unified Inventory Export
══════════════════════════════════════════════════════════

  [1]  SSI EBG warehouse only
  [2]  SLCI warehouse only
  [3]  Both warehouses (single export, combined)

  [4]  Dual export — PARALLEL  (faster, both jobs run at once)
  [5]  Dual export — SEQUENTIAL (SSI EBG first, then SLCI)

  [C]  Custom node name

Select option:
```

### Which option should I pick?

| Option | When to use |
|--------|------------|
| `1` | You only need the SSI EBG Warehouse file |
| `2` | You only need the SLCI Warehouse file |
| `3` | You need one file with both warehouses combined |
| `4` | **Most common** — you need both files separately, as fast as possible. Triggers both exports at the same time on Ordazzle's server, then downloads both emails. |
| `5` | Same as 4 but one after the other — use if option 4 has issues |

### What happens after you select

1. Chrome opens automatically and logs into Ordazzle
2. Navigates to **Inventory Management → Unified Inventory**
3. Selects the warehouse node(s) and clicks **Apply**
4. Clicks the **Export** button — Ordazzle queues the job and sends an email
5. The popup saying *"Export Inventory Data Request Queued Successfully"* is dismissed automatically
6. The script opens Gmail, searches for the export email, and clicks **Download Template**
7. The file is saved to your **Downloads** folder
8. Chrome closes automatically

> The whole process usually takes **2–5 minutes** depending on how fast Ordazzle sends the email.

### Running without the menu (command line)

```bash
# Single export — specific node names passed directly
python ordazzle_playwright.py SSIEBG_WH_EBGWarehouse

# Dual export — parallel (recommended)
python ordazzle_playwright.py --dual-parallel

# Dual export — sequential
python ordazzle_playwright.py --dual-sequential
```

---

## Step 5 — Run the Web App

The web app lets you upload all channel files and generate the final Excel report in your browser.

From the project root:

```bash
cd "C:\Users\YourName\Desktop\Inventory checking by python"
python "web base app/app.py"
```

Then open your browser and go to:

```
http://localhost:5000
```

### Web App usage flow

| Step | What to do |
|------|-----------|
| **1 — Upload** | Drag and drop your Shopee, Lazada, Zalora, Ordazzle, and SAP files into the upload zones |
| **2 — Configure** | Choose which columns to include, set the Base SKU column, add any comparisons |
| **3 — Download** | Click **Generate & Download Excel** — the report downloads automatically |

If you uploaded files for multiple channels, all reports are bundled into a single `.zip`.

### Sharing the web app on your local network

Anyone on the same WiFi can use it without installing anything:

```bash
python "web base app/app.py"
# → Running on http://0.0.0.0:5000
```

Find your machine's IP address:

```bash
ipconfig
```

Look for **IPv4 Address** under your WiFi adapter (e.g. `192.168.1.5`).  
Share this link with your team: `http://192.168.1.5:5000`

---

## Folder Structure

```
Inventory checking by python/
│
├── .env                          ← YOUR passwords & keys (create this — never share)
├── .env.example                  ← template showing what keys are needed
├── requirements.txt              ← core Python packages
│
├── web base app/
│   ├── app.py                    ← Flask web app (run this for the browser UI)
│   ├── ordazzle_playwright.py    ← Ordazzle export automation
│   ├── shopee_playwright.py      ← Shopee export automation
│   ├── requirements-web.txt      ← web app Python packages
│   └── templates/                ← HTML pages for the web app
│
├── inventory_pkg/
│   ├── channels/                 ← Shopee, Lazada, Zalora file readers
│   ├── readers/                  ← Ordazzle, SAP file readers
│   ├── output/builder.py         ← Excel report builder
│   └── config.py                 ← brand groups, column mappings
│
└── Ordazzle/                     ← downloaded Ordazzle export files land here
```

---

## Troubleshooting

**Chrome opens but gets stuck on the Ordazzle login page**  
→ Double-check `ORDAZZLE_USER` and `ORDAZZLE_PASS` in your `.env` file. Make sure there are no extra spaces.

**"Popup OK not found" in the logs but the script keeps running**  
→ This is fine — it just means Ordazzle dismissed the popup before the script got to it.

**Gmail search finds no email after several minutes**  
→ Check your Gmail Promotions or Spam tab. If the email is there, Gmail's inbox filter is catching it. Either move it to your inbox, or change the search in `.env` by removing `label:inbox` (advanced users only).

**`playwright install chromium` fails**  
→ Run it as administrator: right-click Command Prompt → *Run as administrator*, then retry.

**`pip` says a package is not found**  
→ Make sure Python was added to PATH during install. Re-run the Python installer, choose *Modify*, and tick *Add Python to environment variables*.

**The script finishes but the file is not in `Downloads/`**  
→ Check the terminal logs for the exact saved path — it always prints `✓ File saved to: ...` on success. The file may have been saved under a UUID name (e.g. `839e0e05-....csv`) — this is normal.

---

## Updating the Chrome Profile Path

The Ordazzle script uses a saved Chrome session so it doesn't have to log in every single time. The profile folder is set to:

```
C:\Users\Cedric Bides\AppData\Local\Google\Chrome\PlaywrightProfile
```

If you're running this on a different Windows account, open `ordazzle_playwright.py` and change line ~109:

```python
profile_dir = r"C:\Users\YOUR_WINDOWS_USERNAME\AppData\Local\Google\Chrome\PlaywrightProfile"
```

Replace `YOUR_WINDOWS_USERNAME` with your actual Windows username (the name that appears in `C:\Users\`).