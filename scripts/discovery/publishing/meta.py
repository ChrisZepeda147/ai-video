"""Shared Meta (Facebook / Instagram) OAuth and Graph API helpers."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
META_AUTH_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
RUPLOAD_IG_BASE = f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}"
RUPLOAD_FB_BASE = f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}"
INSTAGRAM_REEL_MAX_BYTES = 300 * 1024 * 1024
INSTAGRAM_CAPTION_LIMIT = 2200
IG_PUBLISH_PERMISSIONS = frozenset({"instagram_content_publish"})
FB_PUBLISH_PERMISSIONS = frozenset({"pages_manage_posts", "publish_video"})


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


def _stringify_graph_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def graph_post(path: str, *, token: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, str] = {"access_token": token}
    for key, value in (data or {}).items():
        if value is None or value == "":
            continue
        payload[key] = _stringify_graph_value(value)
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{GRAPH_BASE}/{path.lstrip('/')}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta Graph API error: {detail}") from exc


def rupload_binary(*, url: str, token: str, path: Path, timeout: int = 300) -> dict[str, Any]:
    size = path.stat().st_size
    request = urllib.request.Request(
        url,
        data=path.read_bytes(),
        method="POST",
        headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(size),
            "Content-Type": "application/octet-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"success": True}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta upload error: {detail}") from exc


def join_caption(*parts: str, limit: int = INSTAGRAM_CAPTION_LIMIT) -> str:
    text = "\n\n".join(str(part).strip() for part in parts if str(part).strip())
    return text[:limit]


def list_granted_permissions(token: str) -> set[str]:
    try:
        payload = graph_get("me/permissions", token=token)
    except Exception:
        return set()
    return {
        str(row.get("permission") or "")
        for row in (payload.get("data") or [])
        if row.get("status") == "granted" and row.get("permission")
    }


def has_publish_permission(token: str, required: frozenset[str] | set[str]) -> bool | None:
    """True/False when Graph returns permissions. None if the token cannot list them."""
    granted = list_granted_permissions(token)
    if not granted:
        return None
    return bool(granted & set(required))


def poll_instagram_container(
    container_id: str,
    *,
    token: str,
    timeout_sec: int = 300,
    interval_sec: float = 5.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = graph_get(container_id, token=token, fields="id,status_code,status")
        code = str(last.get("status_code") or "").upper()
        if code == "FINISHED":
            return last
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram container {code}: {last}")
        time.sleep(interval_sec)
    raise RuntimeError(f"Instagram container still processing after {timeout_sec}s: {last}")


def publish_instagram_reel(
    *,
    ig_user_id: str,
    token: str,
    video_path: str | Path,
    caption: str,
    share_to_feed: bool = True,
    video_url: str | None = None,
    thumb_offset_ms: int | None = None,
    is_ai_generated: bool = False,
) -> dict[str, Any]:
    video = Path(video_path)
    create_data: dict[str, Any] = {
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": share_to_feed,
        "thumb_offset": thumb_offset_ms,
        "is_ai_generated": is_ai_generated or None,
    }
    if video_url:
        create_data["video_url"] = video_url
        container = graph_post(f"{ig_user_id}/media", token=token, data=create_data)
    else:
        if not video.is_file():
            raise FileNotFoundError(f"Video not found: {video}")
        if video.stat().st_size > INSTAGRAM_REEL_MAX_BYTES:
            raise RuntimeError("Instagram Reels max file size is 300MB")
        create_data["upload_type"] = "resumable"
        container = graph_post(f"{ig_user_id}/media", token=token, data=create_data)
        container_id = str(container.get("id") or "")
        upload_uri = str(container.get("uri") or "")
        if not container_id:
            raise RuntimeError(f"Instagram media container missing id: {container}")
        if not upload_uri:
            upload_uri = f"{RUPLOAD_IG_BASE}/{container_id}"
        uploaded = rupload_binary(url=upload_uri, token=token, path=video)
        if uploaded.get("success") is False:
            raise RuntimeError(f"Instagram rupload failed: {uploaded}")

    container_id = str(container.get("id") or "")
    if not container_id:
        raise RuntimeError(f"Instagram media container missing id: {container}")
    poll_instagram_container(container_id, token=token)
    published = graph_post(
        f"{ig_user_id}/media_publish",
        token=token,
        data={"creation_id": container_id},
    )
    media_id = str(published.get("id") or "")
    permalink = None
    if media_id:
        try:
            media = graph_get(media_id, token=token, fields="id,permalink")
            permalink = media.get("permalink")
        except Exception:
            permalink = f"https://www.instagram.com/reel/{media_id}/"
    return {"id": media_id, "permalink": permalink, "container_id": container_id, "raw": published}


def publish_facebook_reel(
    *,
    page_id: str,
    token: str,
    video_path: str | Path,
    title: str,
    description: str,
) -> dict[str, Any]:
    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"Video not found: {video}")
    started = graph_post(f"{page_id}/video_reels", token=token, data={"upload_phase": "start"})
    video_id = str(started.get("video_id") or "")
    upload_url = str(started.get("upload_url") or "")
    if not video_id:
        raise RuntimeError(f"Facebook video_reels start missing video_id: {started}")
    if not upload_url:
        upload_url = f"{RUPLOAD_FB_BASE}/{video_id}"
    rupload_binary(url=upload_url, token=token, path=video)
    finished = graph_post(
        f"{page_id}/video_reels",
        token=token,
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "title": (title or "")[:255] or None,
            "description": (description or "")[:10000] or None,
        },
    )
    permalink = None
    try:
        media = graph_get(video_id, token=token, fields="id,permalink_url")
        permalink = media.get("permalink_url")
    except Exception:
        permalink = f"https://www.facebook.com/reel/{video_id}"
    return {"id": video_id, "permalink": permalink, "raw": finished}


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
