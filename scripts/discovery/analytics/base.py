"""Analytics metrics types — extend publishing providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class PostMetrics:
    platform_post_id: str
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    watch_time_sec: float | None = None
    avg_watch_duration_sec: float | None = None
    completion_rate: float | None = None
    retention: float | None = None
    followers_gained: int | None = None
    impressions: int | None = None
    click_through_rate: float | None = None
    revenue: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_post_id": self.platform_post_id,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "saves": self.saves,
            "watch_time_sec": self.watch_time_sec,
            "avg_watch_duration_sec": self.avg_watch_duration_sec,
            "completion_rate": self.completion_rate,
            "retention": self.retention,
            "followers_gained": self.followers_gained,
            "impressions": self.impressions,
            "click_through_rate": self.click_through_rate,
            "revenue": self.revenue,
            "raw": self.raw,
        }


@dataclass
class AccountMetrics:
    platform_account_id: str
    follower_count: int | None = None
    total_views: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class AnalyticsCapable(Protocol):
    platform: str

    def fetch_post_metrics(
        self, credentials: dict[str, Any], platform_post_id: str
    ) -> PostMetrics: ...

    def fetch_account_metrics(self, credentials: dict[str, Any]) -> AccountMetrics: ...
