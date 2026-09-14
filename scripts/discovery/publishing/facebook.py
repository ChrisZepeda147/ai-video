"""Facebook Page Reels publish + analytics via Meta Graph API."""

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

FACEBOOK_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_manage_posts,publish_video,read_insights"
)


class FacebookPublishingProvider:
    platform = "facebook"

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart:
        return OAuthStart(
            auth_url=meta_api.meta_auth_url(
                redirect_uri=redirect_uri,
                state=state,
                scopes=FACEBOOK_SCOPES,
            ),
            state=state,
            instructions=(
                "Connect a Facebook Page linked to this Meta app. "
                "Reconnect after this update so Reels publish scope is granted."
            ),
        )

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]:
        payload = meta_api.complete_meta_connect(redirect_uri=redirect_uri, code=code)
        page = meta_api.pick_page(payload.get("pages") or [], prefer_instagram=False)
        if not page:
            raise RuntimeError(
                "No Facebook Pages found for this account. "
                "Create or assign a Page in Meta Business Suite first."
            )
        creds = {
            "access_token": payload["access_token"],
            "expires_at": payload.get("expires_at"),
            "page_id": str(page.get("id") or ""),
            "page_name": str(page.get("name") or ""),
            "page_access_token": str(page.get("access_token") or payload["access_token"]),
        }
        return creds

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return credentials

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        user_token = credentials.get("access_token") or token
        page_id = credentials.get("page_id")
        if not token or not page_id:
            return AccountVerification(
                ok=False,
                auth_status="disconnected",
                posting_available=False,
                message="Missing Facebook Page credentials",
            )
        try:
            profile = meta_api.graph_get(
                str(page_id),
                token=str(token),
                fields="id,name,fan_count,followers_count",
            )
        except Exception as exc:
            return AccountVerification(
                ok=False,
                auth_status="error",
                posting_available=False,
                message=str(exc),
            )
        publish_ok = meta_api.has_publish_permission(
            str(user_token), meta_api.FB_PUBLISH_PERMISSIONS
        )
        if publish_ok is False:
            return AccountVerification(
                ok=True,
                username=str(profile.get("name") or credentials.get("page_name") or ""),
                platform_account_id=str(profile.get("id") or page_id),
                posting_available=False,
                auth_status="connected",
                capabilities={"analytics": True, "upload": False, "reels": False},
                audit_note="Reconnect Facebook to grant Reels publish (pages_manage_posts).",
            )
        return AccountVerification(
            ok=True,
            username=str(profile.get("name") or credentials.get("page_name") or ""),
            platform_account_id=str(profile.get("id") or page_id),
            posting_available=True,
            auth_status="connected",
            capabilities={"analytics": True, "upload": True, "reels": True},
        )

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult:
        page_id = str(credentials.get("page_id") or "")
        token = str(credentials.get("page_access_token") or credentials.get("access_token") or "")
        if not page_id or not token:
            raise RuntimeError("Missing Facebook Page credentials")
        video = Path(request.video_path)
        if not video.is_file():
            raise FileNotFoundError(f"Video not found: {video}")
        description = meta_api.join_caption(request.caption, request.hashtags, limit=10000)
        published = meta_api.publish_facebook_reel(
            page_id=page_id,
            token=token,
            video_path=video,
            title=request.title,
            description=description,
        )
        video_id = str(published.get("id") or "")
        if not video_id:
            raise RuntimeError(f"Facebook video_reels returned no video_id: {published}")
        return PublishResult(
            platform_post_id=video_id,
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
                fields="id,permalink_url,status",
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def fetch_post_metrics(self, credentials: dict[str, Any], platform_post_id: str) -> PostMetrics:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        if not token:
            return PostMetrics(platform_post_id=platform_post_id, raw={"error": "missing_token"})
        try:
            post = meta_api.graph_get(
                platform_post_id,
                token=str(token),
                fields="id,shares,comments.summary(true),reactions.summary(true)",
            )
            reactions = (post.get("reactions") or {}).get("summary") or {}
            comments = (post.get("comments") or {}).get("summary") or {}
            insights = meta_api.graph_get(
                f"{platform_post_id}/insights",
                token=str(token),
                fields="name,values",
            )
            views = None
            for row in insights.get("data") or []:
                if row.get("name") in {"post_impressions", "post_video_views"}:
                    values = row.get("values") or []
                    if values:
                        views = int(values[-1].get("value") or 0)
            return PostMetrics(
                platform_post_id=platform_post_id,
                views=views,
                likes=int(reactions.get("total_count") or 0) if reactions.get("total_count") is not None else None,
                comments=int(comments.get("total_count") or 0) if comments.get("total_count") is not None else None,
                shares=int((post.get("shares") or {}).get("count") or 0) if post.get("shares") else None,
                raw={"post": post, "insights": insights},
            )
        except Exception as exc:
            return PostMetrics(platform_post_id=platform_post_id, raw={"error": str(exc)})

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics:
        token = credentials.get("page_access_token") or credentials.get("access_token")
        page_id = credentials.get("page_id")
        if not token or not page_id:
            return AccountMetrics(platform_account_id=str(page_id or ""), raw={"error": "missing_token"})
        try:
            profile = meta_api.graph_get(
                str(page_id),
                token=str(token),
                fields="id,fan_count,followers_count",
            )
            followers = profile.get("followers_count") or profile.get("fan_count")
            return AccountMetrics(
                platform_account_id=str(page_id),
                follower_count=int(followers) if followers is not None else None,
                raw={"profile": profile},
            )
        except Exception as exc:
            return AccountMetrics(platform_account_id=str(page_id), raw={"error": str(exc)})
