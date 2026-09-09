"""Instagram Reels publishing — official Meta API architecture with clear setup gaps."""

from __future__ import annotations

from typing import Any

from discovery.analytics.base import AccountMetrics, PostMetrics
from discovery.publishing.base import (
    AccountVerification,
    OAuthStart,
    PublishRequest,
    PublishResult,
)

INSTAGRAM_SETUP_NOTE = (
    "Instagram Reels publishing requires a Meta developer app with "
    "instagram_content_publish permission, a connected Instagram Business/Creator account, "
    "and Facebook Page linkage. Configure META_APP_ID, META_APP_SECRET, and complete Meta OAuth "
    "before live publishing. Provider architecture is ready; external app setup is still required."
)


class InstagramPublishingProvider:
    platform = "instagram"

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart:
        return OAuthStart(
            auth_url=f"https://www.facebook.com/v18.0/dialog/oauth?state={state}",
            state=state,
            instructions=INSTAGRAM_SETUP_NOTE,
        )

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(INSTAGRAM_SETUP_NOTE)

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(INSTAGRAM_SETUP_NOTE)

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification:
        if credentials.get("access_token"):
            return AccountVerification(
                ok=True,
                username=credentials.get("username"),
                platform_account_id=credentials.get("platform_account_id"),
                posting_available=False,
                auth_status="connected",
                capabilities={"reels": False},
                audit_note=INSTAGRAM_SETUP_NOTE,
            )
        return AccountVerification(
            ok=False,
            auth_status="disconnected",
            posting_available=False,
            message=INSTAGRAM_SETUP_NOTE,
            audit_note=INSTAGRAM_SETUP_NOTE,
        )

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult:
        raise RuntimeError(INSTAGRAM_SETUP_NOTE)

    def fetch_publish_status(self, credentials: dict[str, Any], platform_post_id: str) -> dict[str, Any]:
        return {"status": "not_configured", "message": INSTAGRAM_SETUP_NOTE}

    def fetch_post_metrics(self, credentials: dict[str, Any], platform_post_id: str) -> PostMetrics:
        return PostMetrics(
            platform_post_id=platform_post_id,
            raw={"status": "not_configured", "message": INSTAGRAM_SETUP_NOTE},
        )

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics:
        return AccountMetrics(
            platform_account_id=str(credentials.get("platform_account_id") or ""),
            raw={"status": "not_configured", "message": INSTAGRAM_SETUP_NOTE},
        )
