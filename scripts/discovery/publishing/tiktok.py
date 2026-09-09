"""TikTok publishing — reuses scripts/tiktok_upload.py HTTP/upload helpers."""

from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from discovery.analytics.base import AccountMetrics, PostMetrics
from discovery.publishing.base import (
    AccountVerification,
    OAuthStart,
    PublishRequest,
    PublishResult,
)

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tiktok_upload as tt  # noqa: E402


class TikTokPublishingProvider:
    platform = "tiktok"

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart:
        key, _secret, redirect = tt._client_credentials()
        verifier, challenge = tt._pkce_pair()
        params = {
            "client_key": key,
            "response_type": "code",
            "scope": tt.DEFAULT_SCOPES,
            "redirect_uri": redirect_uri or redirect,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{tt.AUTHORIZE_URL}?{urlencode(params)}"
        unaudited = (
            "TikTok apps without audit may only post privately (SELF_ONLY). "
            "Public posting requires TikTok developer app review."
        )
        return OAuthStart(
            auth_url=auth_url,
            state=state,
            instructions=unaudited,
        )

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]:
        key, secret, redirect = tt._client_credentials()
        verifier = state_data.get("code_verifier") or ""
        payload = tt._http_json(
            "POST",
            f"{tt.API_BASE}/v2/oauth/token/",
            form={
                "client_key": key,
                "client_secret": secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri or redirect,
                "code_verifier": verifier,
            },
        )
        if not payload.get("access_token"):
            raise RuntimeError(f"TikTok token exchange failed: {payload}")
        now = int(time.time())
        return {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", ""),
            "open_id": payload.get("open_id", ""),
            "scope": payload.get("scope", ""),
            "expires_at": now + int(payload.get("expires_in") or 0),
            "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 0),
            "code_verifier": verifier,
        }

    def _access_token(self, credentials: dict[str, Any]) -> str:
        if int(credentials.get("expires_at") or 0) <= int(time.time()) + 60:
            credentials = self.refresh_credentials(credentials)
        token = credentials.get("access_token") or ""
        if not token:
            raise RuntimeError("TikTok account missing access_token")
        return token

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        key, secret, _redirect = tt._client_credentials()
        refresh = credentials.get("refresh_token") or ""
        if not refresh:
            raise RuntimeError("TikTok refresh_token missing — reconnect account")
        payload = tt._http_json(
            "POST",
            f"{tt.API_BASE}/v2/oauth/token/",
            form={
                "client_key": key,
                "client_secret": secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
        )
        if not payload.get("access_token"):
            raise RuntimeError(f"TikTok token refresh failed: {payload}")
        now = int(time.time())
        updated = dict(credentials)
        updated.update(
            {
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token") or refresh,
                "expires_at": now + int(payload.get("expires_in") or 0),
                "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 0),
            }
        )
        return updated

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification:
        try:
            token = self._access_token(credentials)
            creator = tt.query_creator(token)
        except Exception as exc:
            return AccountVerification(
                ok=False,
                auth_status="error",
                posting_available=False,
                message=str(exc),
                audit_note=(
                    "TikTok unaudited apps are restricted to private posting. "
                    "Request Content Posting API audit for PUBLIC_TO_EVERYONE."
                ),
            )
        privacy_options = creator.get("privacy_level_options") or []
        public_ok = "PUBLIC_TO_EVERYONE" in privacy_options
        username = creator.get("creator_username") or credentials.get("username")
        return AccountVerification(
            ok=True,
            username=str(username) if username else None,
            platform_account_id=str(credentials.get("open_id") or ""),
            posting_available=True,
            auth_status="connected",
            capabilities={
                "privacy_level_options": privacy_options,
                "public_posting": public_ok,
                "duet": not creator.get("duet_disabled"),
                "comment": not creator.get("comment_disabled"),
                "stitch": not creator.get("stitch_disabled"),
            },
            audit_note=None if public_ok else "App unaudited — public posting unavailable via API",
            token_expires_at=str(credentials.get("expires_at")),
        )

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult:
        token = self._access_token(credentials)
        creator = tt.query_creator(token)
        privacy = request.metadata.get("privacy_level") or "SELF_ONLY"
        privacy = tt.resolve_privacy(str(privacy), creator)
        caption = tt.join_caption(
            [request.title, request.caption, request.hashtags],
            limit=tt.VIDEO_CAPTION_LIMIT,
        )
        video = Path(request.video_path)
        if not video.is_file():
            raise FileNotFoundError(f"Video not found: {video}")
        size = video.stat().st_size
        chunk = tt.CHUNK_SIZE if size > tt.CHUNK_SIZE else size
        body = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy,
                "disable_duet": bool(request.metadata.get("disable_duet")),
                "disable_comment": bool(request.metadata.get("disable_comment")),
                "disable_stitch": bool(request.metadata.get("disable_stitch")),
                "video_cover_timestamp_ms": tt.COVER_FRAME_MS,
                "brand_content_toggle": False,
                "brand_organic_toggle": False,
                "is_aigc": bool(request.metadata.get("is_aigc", True)),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk,
                "total_chunk_count": max(1, (size + chunk - 1) // chunk) if chunk else 1,
            },
        }
        init = tt._api_data(
            tt._http_json(
                "POST",
                f"{tt.API_BASE}/v2/post/publish/video/init/",
                token=token,
                body=body,
            )
        )
        publish_id = str(init.get("publish_id") or "")
        upload_url = str(init.get("upload_url") or "")
        if not publish_id or not upload_url:
            raise RuntimeError(f"TikTok video/init failed: {init}")
        tt.put_file_chunks(upload_url, video)
        status = tt.poll_status(token, publish_id)
        final_status = str(status.get("status") or "")
        if final_status == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {status}")
        return PublishResult(
            platform_post_id=publish_id,
            platform_url=status.get("publicaly_available_post_id") or None,
            status="published" if final_status == "PUBLISH_COMPLETE" else "processing",
            processing_status=final_status,
            raw=status,
        )

    def fetch_publish_status(self, credentials: dict[str, Any], platform_post_id: str) -> dict[str, Any]:
        token = self._access_token(credentials)
        return tt.fetch_status(token, platform_post_id)

    def fetch_post_metrics(self, credentials: dict[str, Any], platform_post_id: str) -> PostMetrics:
        token = self._access_token(credentials)
        try:
            data = tt._api_data(
                tt._http_json(
                    "POST",
                    f"{tt.API_BASE}/v2/video/query/",
                    token=token,
                    body={"filters": {"video_ids": [platform_post_id]}},
                )
            )
            videos = (data.get("videos") or []) if isinstance(data, dict) else []
            item = videos[0] if videos else {}
            return PostMetrics(
                platform_post_id=platform_post_id,
                views=item.get("view_count"),
                likes=item.get("like_count"),
                comments=item.get("comment_count"),
                shares=item.get("share_count"),
                raw={"tiktok": data},
            )
        except Exception as exc:
            return PostMetrics(
                platform_post_id=platform_post_id,
                raw={"error": str(exc), "note": "TikTok analytics may require additional API scopes"},
            )

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics:
        return AccountMetrics(
            platform_account_id=str(credentials.get("platform_account_id") or ""),
            raw={"note": "TikTok account metrics require creator analytics API access"},
        )
