# Inventory Checker — Web App

Browser-based replacement for the tkinter GUI. Upload files, configure columns, download Excel — no Python environment needed on the user's machine.

---

## Project Layout

```
[project root]/
├── inventory_pkg/        ← existing package (UNCHANGED)
├── web_app/
│   ├── app.py            ← Flask application
│   ├── templates/
│   │   ├── base.html
│   │   ├── upload.html
│   │   └── configure.html
│   └── requirements-web.txt
├── requirements.txt      ← original dependencies
└── ...
```

---

## Setup

```bash
# 1. Install Flask (alongside your existing deps)
pip install flask werkzeug

# Or install everything at once:
pip install -r web_app/requirements-web.txt

# 2. Run from the PROJECT ROOT (important — so inventory_pkg is importable)
cd "Inventory checking by python"
python web_app/app.py

# Or install everything at once:
pip install python-dotenv

# 3. Open in browser
#    http://localhost:5000
```

---

## Usage Flow

| Step | What happens |
|------|-------------|
| **1 — Upload** | Drop channel files (Shopee/Lazada/Zalora), Ordazzle, and SAP exports into the three zones |
| **2 — Configure** | Select which files to process, which columns to include, set Base SKU, add comparisons |
| **3 — Download** | Click "Generate & Download Excel" — file downloads automatically |

Multiple channel files → multiple Excel reports bundled in a single `.zip`.

---

## Running on a Local Network

```bash
# Anyone on the same WiFi can access it:
python web_app/app.py
# → Running on http://0.0.0.0:5000

# Find your machine's IP:
ipconfig       # Windows
ip addr show   # Linux/Mac

# Share: http://192.168.x.x:5000
```

---

## Production / Always-On

For a shared team server (Linux), use `gunicorn`:

```bash
pip install gunicorn
cd "Inventory checking by python"
gunicorn -w 2 -b 0.0.0.0:5000 "web_app.app:app"
```

Or wrap in a systemd service so it starts on boot.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | `dev-secret-change-in-prod` | Flask session signing — **change this in production** |
| `TMPDIR` | `/tmp` | Where uploaded files are stored during processing |

```bash
SECRET_KEY="your-random-string" python web_app/app.py
```

---

## What Didn't Change

All core logic is untouched:
- `inventory_pkg/channels/` — Shopee, Lazada, Zalora readers
- `inventory_pkg/readers/` — Ordazzle, SAP readers
- `inventory_pkg/output/builder.py` — Excel builder
- `inventory_pkg/config.py` — brand groups, credentials, file patterns

The web app is purely a new frontend that calls the same functions the tkinter GUI called.