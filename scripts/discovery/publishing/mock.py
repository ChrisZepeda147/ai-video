"""Mock publishing provider for tests and dry-run mode."""

from __future__ import annotations

import secrets
import time
from typing import Any

from discovery.analytics.base import AccountMetrics, PostMetrics
from discovery.publishing.base import (
    AccountVerification,
    OAuthStart,
    PublishRequest,
    PublishResult,
)


class MockPublishingProvider:
    platform: str

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart:
        return OAuthStart(
            auth_url=f"https://mock.example/{self.platform}/oauth?state={state}",
            state=state,
            instructions="Mock OAuth — use complete_connect with any code in tests.",
        )

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "access_token": f"mock-{self.platform}-{secrets.token_hex(8)}",
            "refresh_token": f"mock-refresh-{secrets.token_hex(8)}",
            "platform_account_id": f"mock_{self.platform}_123",
            "username": state_data.get("username") or f"mock_{self.platform}",
            "expires_at": int(time.time()) + 3600,
        }

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        updated = dict(credentials)
        updated["access_token"] = f"mock-refreshed-{secrets.token_hex(6)}"
        updated["expires_at"] = int(time.time()) + 3600
        return updated

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification:
        return AccountVerification(
            ok=bool(credentials.get("access_token")),
            username=credentials.get("username"),
            platform_account_id=credentials.get("platform_account_id"),
            posting_available=True,
            auth_status="connected",
            capabilities={"mock": True, "public_posting": True},
            audit_note=None,
        )

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult:
        post_id = f"mock_{self.platform}_{secrets.token_hex(6)}"
        return PublishResult(
            platform_post_id=post_id,
            platform_url=f"https://mock.example/{self.platform}/{post_id}",
            status="published",
            processing_status="complete",
            raw={"title": request.title, "dry_run": True},
        )

    def fetch_publish_status(self, credentials: dict[str, Any], platform_post_id: str) -> dict[str, Any]:
        return {"status": "PUBLISH_COMPLETE", "platform_post_id": platform_post_id}

    def fetch_post_metrics(self, credentials: dict[str, Any], platform_post_id: str) -> PostMetrics:
        import hashlib

        digest = hashlib.md5(platform_post_id.encode()).hexdigest()
        seed = int(digest[:8], 16)
        views = 3000 + (seed % 120_000)
        likes = int(views * (0.04 + (seed % 30) / 1000))
        comments = int(views * (0.002 + (seed % 10) / 5000))
        shares = int(views * (0.001 + (seed % 8) / 8000))
        completion = round(0.35 + (seed % 40) / 100, 3)
        return PostMetrics(
            platform_post_id=platform_post_id,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            saves=int(shares * 0.8),
            avg_watch_duration_sec=round(18 + (seed % 25), 1),
            completion_rate=completion,
            impressions=int(views * 1.4),
            raw={"mock": True, "platform": self.platform},
        )

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics:
        return AccountMetrics(
            platform_account_id=str(credentials.get("platform_account_id") or "mock"),
            follower_count=10_000 + len(str(credentials.get("username") or "")) * 100,
            total_views=500_000,
            raw={"mock": True},
        )
