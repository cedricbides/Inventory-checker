"""Shopee inventory pull endpoints."""

import logging

from flask import Blueprint

from routes.auth_routes import login_required
from routes.pull_helpers import register_pull_routes
from shopee_reader import get_inventory

log = logging.getLogger(__name__)
shopee_bp = Blueprint("shopee", __name__)

register_pull_routes(
    shopee_bp,
    channel="shopee",
    mp_type="shopee",
    channel_label="Shopee",
    filename_prefix="Shopee_Inventory",
    fetch_rows=get_inventory,
    login_required=login_required,
)
