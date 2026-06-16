"""
credentials.py

Loads Zalora API keys from environment variables (set in .env or server env).
Never hardcode keys here — add them to .env instead (gitignored).

Format in .env:
    ZALORA_BRANDNAME_ID=xxxx
    ZALORA_BRANDNAME_SECRET=xxxx

Brand name rules: uppercase, spaces → underscores, hyphens → underscores
    "Banana Republic" → ZALORA_BANANA_REPUBLIC
    "FFS-CSQ"        → ZALORA_FFS_CSQ
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads .env from project root

def _key(brand: str) -> str:
    """Turn a brand name into an env var prefix."""
    return "ZALORA_" + brand.upper().replace(" ", "_").replace("-", "_")

_BRANDS = [
    "Banana Republic",
    "FFS-CSQ",
    "FFS-Rockwell",
    "FFW",
    "Gap",
    "Lacoste",
    "Lush",
    "MakeRoom",
    "Old Navy",
    "Payless",
    "Polo Ralph Lauren",
    "Pomelo",
]

ZALORA_CREDENTIALS = {}
for brand in _BRANDS:
    prefix = _key(brand)
    client_id        = os.getenv(f"{prefix}_ID")
    client_secret = os.getenv(f"{prefix}_SECRET")
    if client_id and client_secret:
        ZALORA_CREDENTIALS[brand] = {
            "client_id":     client_id,
            "client_secret": client_secret,
        }