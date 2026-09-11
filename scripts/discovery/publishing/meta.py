"""Shared Meta (Facebook / Instagram) OAuth and Graph API helpers."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
META_AUTH_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"


def meta_app_config() -> tuple[str, str]:
    app_id = os.environ.get("META_APP_ID", "").strip()
    app_secret = os.environ.get("META_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError(
            "Missing META_APP_ID or META_APP_SECRET in scripts/.env — "
            "create a Meta developer app and add OAuth redirect "
            "http://localhost:3000/accounts/callback"
        )
    return app_id, app_secret


def meta_auth_url(*, redirect_uri: str, state: str, scopes: str) -> str:
    app_id, _secret = meta_app_config()
    params = urllib.parse.urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scopes,
            "response_type": "code",
        }
    )
    return f"{META_AUTH_URL}?{params}"


def _http_get(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta Graph API error: {detail}") from exc


def exchange_code_for_token(*, redirect_uri: str, code: str) -> dict[str, Any]:
    app_id, app_secret = meta_app_config()
    params = urllib.parse.urlencode(
        {
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
    )
    return _http_get(f"{GRAPH_BASE}/oauth/access_token?{params}")


def exchange_long_lived_token(short_token: str) -> dict[str, Any]:
    app_id, app_secret = meta_app_config()
    params = urllib.parse.urlencode(
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }
    )
    return _http_get(f"{GRAPH_BASE}/oauth/access_token?{params}")


def list_managed_pages(user_token: str) -> list[dict[str, Any]]:
    fields = "id,name,access_token,instagram_business_account{id,username}"
    params = urllib.parse.urlencode({"fields": fields, "access_token": user_token})
    payload = _http_get(f"{GRAPH_BASE}/me/accounts?{params}")
    return list(payload.get("data") or [])


def graph_get(path: str, *, token: str, fields: str | None = None) -> dict[str, Any]:
    params: dict[str, str] = {"access_token": token}
    if fields:
        params["fields"] = fields
    query = urllib.parse.urlencode(params)
    return _http_get(f"{GRAPH_BASE}/{path}?{query}")


def complete_meta_connect(*, redirect_uri: str, code: str) -> dict[str, Any]:
    short = exchange_code_for_token(redirect_uri=redirect_uri, code=code)
    short_token = str(short.get("access_token") or "")
    if not short_token:
        raise RuntimeError(f"Meta token exchange failed: {short}")
    long = exchange_long_lived_token(short_token)
    access_token = str(long.get("access_token") or short_token)
    expires_in = int(long.get("expires_in") or short.get("expires_in") or 0)
    pages = list_managed_pages(access_token)
    return {
        "access_token": access_token,
        "expires_at": int(time.time()) + expires_in if expires_in else 0,
        "pages": pages,
    }


def pick_page(pages: list[dict[str, Any]], *, prefer_instagram: bool) -> dict[str, Any] | None:
    if not pages:
        return None
    if prefer_instagram:
        for page in pages:
            ig = page.get("instagram_business_account") or {}
            if ig.get("id"):
                return page
    return pages[0]


def instagram_business_from_page(page: dict[str, Any]) -> dict[str, Any]:
    return dict(page.get("instagram_business_account") or {})
