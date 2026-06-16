"""Lazada inventory pull endpoints."""

import logging

from flask import Blueprint

from routes.auth_routes import login_required
from routes.pull_helpers import register_pull_routes
from lazada_reader import get_inventory

log = logging.getLogger(__name__)
lazada_bp = Blueprint("lazada", __name__)

register_pull_routes(
    lazada_bp,
    channel="lazada",
    mp_type="lazada",
    channel_label="Lazada",
    filename_prefix="Lazada_Inventory",
    fetch_rows=get_inventory,
    login_required=login_required,
)
