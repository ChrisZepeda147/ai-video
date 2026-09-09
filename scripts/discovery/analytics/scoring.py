"""Performance scoring and account-relative normalization."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


TIERS = ("underperforming", "average", "strong", "breakout")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def post_age_days(published_at: str | None) -> float:
    pub = _parse_iso(published_at)
    if not pub:
        return 1.0
    delta = datetime.now(timezone.utc) - pub
    return max(delta.total_seconds() / 86400.0, 0.04)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def engagement_rate(metrics: dict[str, Any]) -> float:
    views = float(metrics.get("views") or 0)
    if views <= 0:
        return 0.0
    likes = float(metrics.get("likes") or 0)
    comments = float(metrics.get("comments") or 0)
    shares = float(metrics.get("shares") or 0)
    saves = float(metrics.get("saves") or 0)
    return (likes + comments + shares + saves) / views


def score_post_performance(
    metrics: dict[str, Any],
    *,
    account_baseline_views: float,
    account_baseline_engagement: float,
    published_at: str | None,
) -> dict[str, Any]:
    views = float(metrics.get("views") or 0)
    age_days = post_age_days(published_at)
    velocity = views / age_days if age_days else views
    baseline_views = max(account_baseline_views, 1.0)
    views_vs_median = views / baseline_views
    eng = engagement_rate(metrics)
    eng_vs_baseline = eng / max(account_baseline_engagement, 0.001)

    completion = metrics.get("completion_rate")
    completion_bonus = 0.0
    if completion is not None:
        completion_bonus = min(15.0, float(completion) * 15.0)

    velocity_score = min(35.0, math.log1p(velocity / max(baseline_views / 7.0, 1.0)) * 12.0)
    relative_score = min(35.0, views_vs_median * 12.0)
    engagement_score = min(20.0, eng_vs_baseline * 10.0)
    score = max(0.0, min(100.0, velocity_score + relative_score + engagement_score + completion_bonus))

    if score >= 85 or views_vs_median >= 2.5:
        tier = "breakout"
    elif score >= 70 or views_vs_median >= 1.5:
        tier = "strong"
    elif score >= 40:
        tier = "average"
    else:
        tier = "underperforming"

    return {
        "performance_score": round(score, 1),
        "performance_tier": tier,
        "views_vs_account_median": round(views_vs_median, 3),
        "velocity_views_per_day": round(velocity, 1),
        "engagement_rate": round(eng, 4),
    }


def performance_signals(
    score_data: dict[str, Any],
    features: dict[str, Any],
) -> list[str]:
    """Advisory wording — associated with, not causation."""
    signals: list[str] = []
    if score_data.get("velocity_views_per_day", 0) > 5000:
        signals.append("Strong first-period velocity associated with higher performance")
    if score_data.get("views_vs_account_median", 0) >= 1.5:
        signals.append("Views above recent account baseline")
    if features.get("hook_formula"):
        signals.append(f"Hook formula '{features['hook_formula']}' present on this post")
    if features.get("format_profile"):
        signals.append(f"Format profile '{features['format_profile']}' used")
    if features.get("niche"):
        signals.append(f"Niche '{features['niche']}' category")
    return signals
