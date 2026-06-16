"""Shared Zalora HTTP helpers for zalora_pull and zalora_reader."""

import logging

import requests

log = logging.getLogger(__name__)

ZALORA_HOST = "https://sellercenter-api.zalora.com.ph/"
PAGE_SIZE = 100


def get_token(client_id: str, client_secret: str) -> str:
    r = requests.post(
        ZALORA_HOST + "oauth/client-credentials",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def emit(progress_cb, step: str, msg: str, pct: int, *, tag: str = "zalora") -> None:
    if progress_cb:
        progress_cb(step, msg, pct)
    else:
        log.debug("[%s] %s — %s (%d%%)", tag, step, msg, pct)


def paginate(url: str, token: str, params: dict | None = None) -> list:
    """Fetch all pages from a Zalora list endpoint."""
    results = []
    page = 1
    base = params or {}

    while True:
        r = requests.get(
            url,
            headers=auth_headers(token),
            params={**base, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        items = (
            body.get("data")
            or body.get("items")
            or body.get("orders")
            or body.get("payouts")
            or (body if isinstance(body, list) else [])
        )
        if not items:
            break
        results.extend(items)
        if len(items) < PAGE_SIZE:
            break
        page += 1

    return results


def mp_credentials(mp: dict) -> tuple[str, str, str]:
    """Return (brand, client_id, client_secret) from a marketplace settings dict."""
    brand = (mp.get("brand") or "").strip()
    return brand, mp.get("client_id", ""), mp.get("client_secret", "")
