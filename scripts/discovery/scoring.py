"""Virality scoring for reference videos (internal ranking, not scientific)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def parse_published_at(value: str | None, *, now: datetime | None = None) -> datetime | None:
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def age_hours_since_published(published_at: str | None, *, now: datetime | None = None) -> float | None:
    published = parse_published_at(published_at, now=now)
    if published is None:
        return None
    now = now or datetime.now(timezone.utc)
    delta = now - published
    return max(delta.total_seconds() / 3600.0, 1.0)


@dataclass
class ViralityMetrics:
    age_hours: float | None
    age_days: float | None
    views_per_day: float | None
    views_per_hour: float | None
    like_ratio: float | None
    comment_ratio: float | None
    velocity_component: float
    recency_component: float
    engagement_component: float
    virality_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_hours": self.age_hours,
            "age_days": self.age_days,
            "views_per_day": self.views_per_day,
            "views_per_hour": self.views_per_hour,
            "like_ratio": self.like_ratio,
            "comment_ratio": self.comment_ratio,
            "velocity_component": self.velocity_component,
            "recency_component": self.recency_component,
            "engagement_component": self.engagement_component,
            "virality_score": self.virality_score,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _velocity_score(views_per_day: float | None, views_per_hour: float | None, age_hours: float | None) -> float:
    if views_per_day is None or views_per_day <= 0:
        return 0.0
    # Log-scaled daily velocity — rewards fast growth without unbounded spikes.
    daily = _clamp(math.log10(views_per_day + 1) * 10.0, 0.0, 42.0)
    hourly_bonus = 0.0
    if views_per_hour and age_hours is not None and age_hours <= 72:
        hourly_bonus = _clamp(math.log10(views_per_hour + 1) * 4.0, 0.0, 8.0)
    return _clamp(daily + hourly_bonus, 0.0, 50.0)


def _recency_score(age_hours: float | None) -> float:
    if age_hours is None:
        return 5.0
    if age_hours <= 24:
        return 25.0
    if age_hours <= 72:
        return 20.0
    if age_hours <= 24 * 7:
        return 15.0
    if age_hours <= 24 * 30:
        return 8.0
    if age_hours <= 24 * 365:
        return 4.0
    return 2.0


def _engagement_score(
    view_count: int | None,
    like_ratio: float | None,
    comment_ratio: float | None,
) -> float:
    if not view_count or view_count < 10_000:
        return 0.0
    like_part = 0.0
    comment_part = 0.0
    if like_ratio is not None and like_ratio > 0:
        like_part = _clamp(like_ratio / 0.06, 0.0, 1.0) * 15.0
    if comment_ratio is not None and comment_ratio > 0:
        comment_part = _clamp(comment_ratio / 0.01, 0.0, 1.0) * 10.0
    raw = like_part + comment_part
    # Scale down engagement for smaller channels so odd ratios do not dominate.
    view_scale = _clamp(math.log10(max(view_count, 1)) / 6.0, 0.35, 1.0)
    return _clamp(raw * view_scale, 0.0, 25.0)


def compute_virality_metrics(
    *,
    view_count: int | None,
    like_count: int | None,
    comment_count: int | None,
    published_at: str | None,
    now: datetime | None = None,
) -> ViralityMetrics:
    """Return normalized virality score (0–100) and raw components."""
    now = now or datetime.now(timezone.utc)
    age_h = age_hours_since_published(published_at, now=now)
    age_d = age_h / 24.0 if age_h is not None else None

    views_per_day: float | None = None
    views_per_hour: float | None = None
    if view_count is not None and view_count >= 0 and age_h is not None:
        views_per_hour = view_count / max(age_h, 1.0)
        views_per_day = view_count / max(age_d or (age_h / 24.0), 1.0 / 24.0)

    like_ratio: float | None = None
    comment_ratio: float | None = None
    if view_count and view_count > 0:
        if like_count is not None:
            like_ratio = like_count / view_count
        if comment_count is not None:
            comment_ratio = comment_count / view_count

    velocity = _velocity_score(views_per_day, views_per_hour, age_h)
    recency = _recency_score(age_h)
    engagement = _engagement_score(view_count, like_ratio, comment_ratio)
    score = _clamp(round(velocity + recency + engagement, 2), 0.0, 100.0)

    return ViralityMetrics(
        age_hours=round(age_h, 2) if age_h is not None else None,
        age_days=round(age_d, 3) if age_d is not None else None,
        views_per_day=round(views_per_day, 2) if views_per_day is not None else None,
        views_per_hour=round(views_per_hour, 2) if views_per_hour is not None else None,
        like_ratio=round(like_ratio, 6) if like_ratio is not None else None,
        comment_ratio=round(comment_ratio, 6) if comment_ratio is not None else None,
        velocity_component=round(velocity, 2),
        recency_component=round(recency, 2),
        engagement_component=round(engagement, 2),
        virality_score=score,
    )
