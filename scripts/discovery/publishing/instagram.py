"""Instagram Business Reels publish + analytics via Meta Graph API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from discovery.analytics.base import AccountMetrics, PostMetrics
from discovery.publishing.base import (
    AccountVerification,
    OAuthStart,
    PublishRequest,
    PublishResult,
)
from discovery.publishing import meta as meta_api

INSTAGRAM_SCOPES = (
    "instagram_basic,instagram_content_publish,instagram_manage_insights,"
    "pages_show_list,pages_read_engagement,pages_manage_posts"
)


class InstagramPublishingProvider:
    platform = "instagram"

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart:
        return OAuthStart(
            auth_url=meta_api.meta_auth_url(
                redirect_uri=redirect_uri,
                state=state,
                scopes=INSTAGRAM_SCOPES,
            ),
            state=state,
            instructions=(
                "Connect an Instagram Business account linked to a Facebook Page. "
                "Meta OAuth opens on facebook.com — that is expected. "
                "Reconnect after this update so Reels publish scope is granted."
            ),
        )

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]:
        payload = meta_api.complete_meta_connect(redirect_uri=redirect_uri, code=code)
        page = meta_api.pick_page(payload.get("pages") or [], prefer_instagram=True)
        if not page:
            raise RuntimeError(
                "No Facebook Page with a linked Instagram Business account was found. "
                "Link IG to a Page in Meta Business Suite, then retry."
            )
        ig = meta_api.instagram_business_from_page(page)
        ig_id = str(ig.get("id") or "")
        if not ig_id:
            raise RuntimeError("Selected Page has no instagram_business_account.")
        return {
            "access_token": payload["access_token"],
            "expires_at": payload.get("expires_at"),
            "page_id": str(page.get("id") or ""),
            "page_access_token": str(page.get("access_token") or payload["access_token"]),
            "platform_account_id": ig_id,
            "username": str(ig.get("username") or ""),
        }

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return credentials

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        user_token = credentials.get("access_token") or token
        ig_id = credentials.get("platform_account_id")
        if not token or not ig_id:
            return AccountVerification(
                ok=False,
                auth_status="disconnected",
                posting_available=False,
                message="Missing Instagram Business credentials",
            )
        try:
            profile = meta_api.graph_get(
                str(ig_id),
                token=str(token),
                fields="id,username,followers_count,media_count",
            )
        except Exception as exc:
            return AccountVerification(
                ok=False,
                auth_status="error",
                posting_available=False,
                message=str(exc),
            )
        publish_ok = meta_api.has_publish_permission(
            str(user_token), meta_api.IG_PUBLISH_PERMISSIONS
        )
        if publish_ok is False:
            return AccountVerification(
                ok=True,
                username=str(profile.get("username") or credentials.get("username") or ""),
                platform_account_id=str(profile.get("id") or ig_id),
                posting_available=False,
                auth_status="connected",
                capabilities={"analytics": True, "reels": False},
                audit_note="Reconnect Instagram to grant Reels publish (instagram_content_publish).",
            )
        return AccountVerification(
            ok=True,
            username=str(profile.get("username") or credentials.get("username") or ""),
            platform_account_id=str(profile.get("id") or ig_id),
            posting_available=True,
            auth_status="connected",
            capabilities={"analytics": True, "reels": True, "upload": True},
        )

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult:
        ig_id = str(credentials.get("platform_account_id") or "")
        token = str(credentials.get("access_token") or credentials.get("page_access_token") or "")
        if not ig_id or not token:
            raise RuntimeError("Missing Instagram Business credentials")
        video = Path(request.video_path)
        if not video.is_file():
            raise FileNotFoundError(f"Video not found: {video}")
        caption = meta_api.join_caption(request.title, request.caption, request.hashtags)
        published = meta_api.publish_instagram_reel(
            ig_user_id=ig_id,
            token=token,
            video_path=video,
            caption=caption,
            share_to_feed=bool(request.metadata.get("share_to_feed", True)),
            video_url=str(request.metadata.get("video_url") or "") or None,
            thumb_offset_ms=request.metadata.get("thumb_offset_ms"),
            is_ai_generated=bool(request.metadata.get("is_aigc", True)),
        )
        media_id = str(published.get("id") or "")
        if not media_id:
            raise RuntimeError(f"Instagram media_publish returned no id: {published}")
        return PublishResult(
            platform_post_id=media_id,
            platform_url=published.get("permalink"),
            status="published",
            processing_status="published",
            raw=published,
        )

    def fetch_publish_status(self, credentials: dict[str, Any], platform_post_id: str) -> dict[str, Any]:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        if not token:
            return {"status": "missing_token"}
        try:
            return meta_api.graph_get(
                platform_post_id,
                token=str(token),
                fields="id,permalink,media_type,timestamp",
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def fetch_post_metrics(self, credentials: dict[str, Any], platform_post_id: str) -> PostMetrics:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        if not token:
            return PostMetrics(platform_post_id=platform_post_id, raw={"error": "missing_token"})
        try:
            media = meta_api.graph_get(
                platform_post_id,
                token=str(token),
                fields="id,like_count,comments_count,permalink",
            )
            views = None
            try:
                insights = meta_api.graph_get(
                    f"{platform_post_id}/insights",
                    token=str(token),
                    fields="name,values",
                )
                for row in insights.get("data") or []:
                    if row.get("name") in {"plays", "video_views", "impressions"}:
                        values = row.get("values") or []
                        if values:
                            views = int(values[-1].get("value") or 0)
            except Exception:
                insights = {}
            return PostMetrics(
                platform_post_id=platform_post_id,
                views=views,
                likes=int(media.get("like_count") or 0) if media.get("like_count") is not None else None,
                comments=int(media.get("comments_count") or 0)
                if media.get("comments_count") is not None
                else None,
                raw={"media": media},
            )
        except Exception as exc:
            return PostMetrics(platform_post_id=platform_post_id, raw={"error": str(exc)})

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        ig_id = credentials.get("platform_account_id")
        if not token or not ig_id:
            return AccountMetrics(platform_account_id=str(ig_id or ""), raw={"error": "missing_token"})
        try:
            profile = meta_api.graph_get(
                str(ig_id),
                token=str(token),
                fields="id,followers_count,media_count",
            )
            return AccountMetrics(
                platform_account_id=str(ig_id),
                follower_count=int(profile.get("followers_count") or 0)
                if profile.get("followers_count") is not None
                else None,
                raw={"profile": profile},
            )
        except Exception as exc:
            return AccountMetrics(platform_account_id=str(ig_id), raw={"error": str(exc)})
