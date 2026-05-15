"""
Thin re-export of the Zalora brand list for use inside the GUI package.
Importing directly from channels.zalora_api would create a heavier dependency
inside the gui package, so we just re-export the key list here.
"""
from ..zalora_api import ZALORA_CREDENTIALS

ZALORA_CRED_BRANDS = sorted(ZALORA_CREDENTIALS.keys())