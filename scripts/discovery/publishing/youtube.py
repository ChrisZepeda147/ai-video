"""YouTube publishing via official YouTube Data API."""

from __future__ import annotations

import json
import os
import secrets
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

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
DEFAULT_SCOPES = f"{YOUTUBE_UPLOAD_SCOPE} {YOUTUBE_READONLY_SCOPE}"


def _client_config() -> tuple[str, str, str]:
    from discovery.config import publishing_oauth_redirect_uri

    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    redirect = os.environ.get("YOUTUBE_REDIRECT_URI", publishing_oauth_redirect_uri()).strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET in scripts/.env"
        )
    return client_id, client_secret, redirect


class YouTubePublishingProvider:
    platform = "youtube"

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart:
        client_id, _secret, default_redirect = _client_config()
        redirect = redirect_uri or default_redirect
        params = {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": DEFAULT_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return OAuthStart(
            auth_url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
            state=state,
            instructions="Connect a YouTube channel with upload scope.",
        )

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        client_id, client_secret, default_redirect = _client_config()
        redirect = redirect_uri or default_redirect
        body = urlencode(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            GOOGLE_TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"YouTube OAuth failed: {detail}") from exc
        now = int(time.time())
        creds = {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token", ""),
            "expires_at": now + int(payload.get("expires_in") or 0),
            "token_type": payload.get("token_type", "Bearer"),
            "scope": payload.get("scope", ""),
        }
        profile = self._channel_profile(creds)
        creds["platform_account_id"] = profile.get("channel_id")
        creds["username"] = profile.get("channel_title")
        return creds

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        client_id, client_secret, _redirect = _client_config()
        refresh = credentials.get("refresh_token") or ""
        if not refresh:
            raise RuntimeError("YouTube refresh_token missing — reconnect account")
        body = urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            GOOGLE_TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"YouTube token refresh failed: {detail}") from exc
        updated = dict(credentials)
        updated["access_token"] = payload.get("access_token")
        updated["expires_at"] = int(time.time()) + int(payload.get("expires_in") or 0)
        return updated

    def _access_token(self, credentials: dict[str, Any]) -> str:
        if int(credentials.get("expires_at") or 0) <= int(time.time()) + 60:
            credentials = self.refresh_credentials(credentials)
        token = credentials.get("access_token") or ""
        if not token:
            raise RuntimeError("YouTube account missing access_token")
        return token

    def _youtube_service(self, credentials: dict[str, Any]):
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise RuntimeError(
                "google-api-python-client is required for YouTube publishing. "
                "Install scripts/requirements-youtube.txt"
            ) from exc
        creds = Credentials(
            token=self._access_token(credentials),
            refresh_token=credentials.get("refresh_token"),
            token_uri=GOOGLE_TOKEN_URL,
            client_id=os.environ.get("YOUTUBE_CLIENT_ID"),
            client_secret=os.environ.get("YOUTUBE_CLIENT_SECRET"),
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def _channel_profile(self, credentials: dict[str, Any]) -> dict[str, str]:
        service = self._youtube_service(credentials)
        response = service.channels().list(part="snippet", mine=True).execute()
        items = response.get("items") or []
        if not items:
            return {"channel_id": "", "channel_title": ""}
        item = items[0]
        return {
            "channel_id": str(item.get("id") or ""),
            "channel_title": str(item.get("snippet", {}).get("title") or ""),
        }

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification:
        try:
            profile = self._channel_profile(credentials)
        except Exception as exc:
            return AccountVerification(
                ok=False,
                auth_status="error",
                posting_available=False,
                message=str(exc),
            )
        return AccountVerification(
            ok=True,
            username=profile.get("channel_title"),
            platform_account_id=profile.get("channel_id"),
            posting_available=True,
            auth_status="connected",
            capabilities={"upload": True, "schedule": True},
        )

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult:
        from googleapiclient.http import MediaFileUpload

        service = self._youtube_service(credentials)
        video = Path(request.video_path)
        if not video.is_file():
            raise FileNotFoundError(f"Video not found: {video}")
        description = request.caption.strip()
        if request.hashtags.strip():
            description = f"{description}\n\n{request.hashtags.strip()}".strip()
        tags = request.metadata.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        body = {
            "snippet": {
                "title": request.title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": str(request.metadata.get("category_id") or "22"),
            },
            "status": {
                "privacyStatus": request.metadata.get("privacy_status") or "private",
                "selfDeclaredMadeForKids": bool(request.metadata.get("made_for_kids", False)),
            },
        }
        scheduled = request.metadata.get("scheduled_at")
        if scheduled:
            body["status"]["publishAt"] = scheduled
            body["status"]["privacyStatus"] = "private"
        media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)
        insert = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = insert.next_chunk()
            if status:
                pass
        video_id = str(response.get("id") or "")
        return PublishResult(
            platform_post_id=video_id,
            platform_url=f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
            status="processing",
            processing_status=str(response.get("status", {}).get("uploadStatus") or "uploaded"),
            raw=response,
        )

    def fetch_publish_status(self, credentials: dict[str, Any], platform_post_id: str) -> dict[str, Any]:
        service = self._youtube_service(credentials)
        return service.videos().list(part="status,processingDetails", id=platform_post_id).execute()

    def fetch_post_metrics(self, credentials: dict[str, Any], platform_post_id: str) -> PostMetrics:
        service = self._youtube_service(credentials)
        response = service.videos().list(part="statistics", id=platform_post_id).execute()
        items = response.get("items") or []
        stats = items[0].get("statistics", {}) if items else {}
        return PostMetrics(
            platform_post_id=platform_post_id,
            views=int(stats.get("viewCount") or 0) if stats.get("viewCount") is not None else None,
            likes=int(stats.get("likeCount") or 0) if stats.get("likeCount") is not None else None,
            comments=int(stats.get("commentCount") or 0) if stats.get("commentCount") is not None else None,
            raw={"statistics": stats},
        )

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics:
        service = self._youtube_service(credentials)
        response = service.channels().list(part="statistics", mine=True).execute()
        items = response.get("items") or []
        stats = items[0].get("statistics", {}) if items else {}
        channel_id = items[0].get("id") if items else ""
        return AccountMetrics(
            platform_account_id=str(channel_id or ""),
            follower_count=int(stats.get("subscriberCount") or 0) if stats.get("subscriberCount") else None,
            total_views=int(stats.get("viewCount") or 0) if stats.get("viewCount") else None,
            raw={"statistics": stats},
        )
