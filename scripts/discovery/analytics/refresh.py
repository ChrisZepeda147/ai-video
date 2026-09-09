"""Pull platform analytics and store historical snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from discovery.analytics.features import extract_project_features
from discovery.analytics.scoring import score_post_performance
from discovery.publishing.credentials import load_credentials
from discovery.publishing.factory import build_publishing_provider
from discovery.store import DiscoveryStore, now_iso


@dataclass
class RefreshResult:
    job_id: int
    refreshed: bool
    snapshot_id: int | None = None
    skipped_reason: str | None = None
    error: str | None = None


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


def refresh_interval_hours(published_at: str | None, *, last_snapshot_at: str | None) -> float:
    """Prioritize recent posts; older stable posts refresh less often."""
    pub = _parse_iso(published_at)
    if not pub:
        return 24.0
    age_days = max((datetime.now(timezone.utc) - pub).total_seconds() / 86400.0, 0.0)
    if age_days <= 3:
        return 6.0
    if age_days <= 14:
        return 24.0
    if age_days <= 60:
        return 168.0
    return 720.0


def should_refresh_job(
    store: DiscoveryStore,
    job_id: int,
    *,
    force: bool = False,
) -> tuple[bool, str | None]:
    if force:
        return True, None
    job = store.get_publishing_job(job_id)
    if not job:
        return False, "job_not_found"
    if job.status not in ("published", "processing") or not job.platform_post_id:
        return False, "not_published"
    latest = store.get_latest_analytics_snapshot(job_id)
    if not latest:
        return True, None
    interval = refresh_interval_hours(job.published_at, last_snapshot_at=latest.snapshot_at)
    last = _parse_iso(latest.snapshot_at)
    if not last:
        return True, None
    elapsed_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
    if elapsed_hours >= interval:
        return True, None
    return False, f"cooldown_{interval}h"


def ensure_post_features(store: DiscoveryStore, job) -> dict[str, Any]:
    existing = store.get_analytics_post_features(job.id)
    if existing:
        return json.loads(existing.features_json)
    features = extract_project_features(store, job)
    store.upsert_analytics_post_features(
        publishing_job_id=job.id,
        production_project_id=job.production_project_id,
        account_id=job.account_id,
        platform=job.platform,
        niche=features.get("niche"),
        hook_formula=features.get("hook_formula"),
        features_json=json.dumps(features),
    )
    return features


def refresh_post_analytics(
    store: DiscoveryStore,
    job_id: int,
    *,
    force: bool = False,
) -> RefreshResult:
    should, reason = should_refresh_job(store, job_id, force=force)
    if not should:
        return RefreshResult(job_id=job_id, refreshed=False, skipped_reason=reason)

    job = store.get_publishing_job(job_id)
    if not job or not job.platform_post_id:
        return RefreshResult(job_id=job_id, refreshed=False, skipped_reason="not_published")

    try:
        provider = build_publishing_provider(job.platform)
        credentials = load_credentials(job.account_id)
        if not credentials.get("access_token"):
            return RefreshResult(job_id=job_id, refreshed=False, error="missing_credentials")

        if not hasattr(provider, "fetch_post_metrics"):
            return RefreshResult(job_id=job_id, refreshed=False, error="analytics_not_supported")

        metrics = provider.fetch_post_metrics(credentials, job.platform_post_id)
        baseline = store.get_account_analytics_baseline(job.account_id)
        score_data = score_post_performance(
            metrics.to_dict(),
            account_baseline_views=baseline["median_views"],
            account_baseline_engagement=baseline["median_engagement"],
            published_at=job.published_at,
        )
        ensure_post_features(store, job)
        snapshot_id = store.insert_analytics_snapshot(
            publishing_job_id=job.id,
            production_project_id=job.production_project_id,
            account_id=job.account_id,
            platform=job.platform,
            platform_post_id=job.platform_post_id,
            metrics=metrics.to_dict(),
            performance=score_data,
        )
        return RefreshResult(job_id=job_id, refreshed=True, snapshot_id=snapshot_id)
    except Exception as exc:
        return RefreshResult(job_id=job_id, refreshed=False, error=str(exc))


def refresh_analytics(
    store: DiscoveryStore,
    *,
    account_id: int | None = None,
    job_id: int | None = None,
    limit: int = 50,
    force: bool = False,
) -> list[RefreshResult]:
    if job_id is not None:
        return [refresh_post_analytics(store, job_id, force=force)]

    jobs = store.list_published_jobs_for_analytics(account_id=account_id, limit=limit)
    results: list[RefreshResult] = []
    for job in jobs:
        results.append(refresh_post_analytics(store, job.id, force=force))
    return results


def analytics_status(store: DiscoveryStore) -> dict[str, Any]:
    jobs = store.list_published_jobs_for_analytics(limit=500)
    latest = store.list_latest_post_snapshots(limit=500)
    tier_counts: dict[str, int] = {}
    for row in latest:
        tier = row.get("performance_tier") or "unknown"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return {
        "published_posts": len(jobs),
        "posts_with_snapshots": len(latest),
        "tier_counts": tier_counts,
        "last_refresh_at": max((r.get("snapshot_at") or "" for r in latest), default=None),
        "generated_at": now_iso(),
    }
