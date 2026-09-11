"""Link existing platform posts to local videos for analytics (no upload)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.publishing.platform_urls import parse_platform_post_url


def _idempotency_key(*parts: str) -> str:
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def ensure_video_project(
    store,
    *,
    slug: str,
    title: str,
    output_path: str | None = None,
    niche: str | None = None,
    origin_type: str = "legacy",
    format_profile: str = "source_video_visuals",
) -> int:
    """Shadow production project so publishing_jobs can attach to any Videos row."""
    existing = store.get_production_project_by_slug(slug)
    if existing:
        if output_path and not existing.output_path:
            root = project_root()
            rel = output_path.replace("\\", "/")
            abs_path = root / rel if not Path(output_path).is_absolute() else Path(output_path)
            if abs_path.is_file():
                store.update_production_project_rendered(
                    existing.id,
                    output_path=rel,
                    duration_sec=0.0,
                    monetization_confidence=1.0,
                    rights_confidence=1.0,
                    reuse_confidence=0.0,
                    risk_explanations_json=json.dumps([]),
                    status="approved",
                )
        return existing.id

    project_id = store.create_production_project(
        slug=slug,
        title=title[:200],
        niche=niche,
        origin_type=origin_type,
        format_profile=format_profile,
        hook_text=None,
        caption_preset="viral_bold",
    )
    if output_path:
        root = project_root()
        rel = output_path.replace("\\", "/")
        abs_path = root / rel if not Path(output_path).is_absolute() else Path(output_path)
        if abs_path.is_file():
            store.update_production_project_rendered(
                project_id,
                output_path=rel,
                duration_sec=0.0,
                monetization_confidence=1.0,
                rights_confidence=1.0,
                reuse_confidence=0.0,
                risk_explanations_json=json.dumps([]),
                status="approved",
            )
    return project_id


def link_video_post(
    store,
    *,
    account_id: int,
    platform_url: str,
    slug: str,
    title: str,
    project_id: int | None = None,
    output_path: str | None = None,
    niche: str | None = None,
    origin_type: str = "legacy",
    format_profile: str = "source_video_visuals",
    refresh_analytics: bool = True,
) -> dict[str, Any]:
    """Record an already-uploaded post for analytics tracking."""
    platform, post_id, normalized_url = parse_platform_post_url(platform_url)
    account = store.get_publishing_account(account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")
    if account.platform != platform:
        raise ValueError(
            f"URL is {platform} but account {account.display_name} is {account.platform}"
        )
    if account.auth_status not in {"connected", "verified"}:
        raise ValueError(f"Account {account.display_name} is not connected ({account.auth_status})")

    pid = project_id or ensure_video_project(
        store,
        slug=slug,
        title=title,
        output_path=output_path,
        niche=niche,
        origin_type=origin_type,
        format_profile=format_profile,
    )
    key = _idempotency_key("link", str(pid), str(account_id), post_id)
    existing = store.get_publishing_job_by_key(key)
    if existing:
        job = existing
        duplicate = True
    else:
        duplicate = False
        job_id = store.create_publishing_job(
            production_project_id=pid,
            account_id=account_id,
            platform=platform,
            idempotency_key=key,
            title=title[:200],
            caption=None,
            hashtags=None,
            metadata_json=json.dumps({"link_only": True, "source_url": normalized_url}),
            scheduled_at=None,
            timezone=None,
            status="published",
        )
        store.complete_publishing_job(
            job_id,
            status="published",
            platform_post_id=post_id,
            platform_url=normalized_url,
        )
        job = store.get_publishing_job(job_id)
        if not job:
            raise ValueError("Failed to create link job")

    refresh_result = None
    if refresh_analytics and not duplicate:
        try:
            from discovery.analytics.refresh import refresh_post_analytics

            refresh_result = refresh_post_analytics(store, job.id, force=True)
        except Exception as exc:
            refresh_result = {"error": str(exc)}

    return {
        "duplicate": duplicate,
        "job_id": job.id,
        "production_project_id": pid,
        "platform": platform,
        "platform_post_id": post_id,
        "platform_url": normalized_url,
        "account_id": account_id,
        "account_display_name": account.display_name,
        "account_owner": account.owner,
        "refresh": (
            {
                "refreshed": refresh_result.refreshed,
                "error": refresh_result.error,
                "skipped_reason": refresh_result.skipped_reason,
            }
            if refresh_result and hasattr(refresh_result, "refreshed")
            else refresh_result
        ),
    }


def publishing_links_for_video(
    store,
    *,
    project_id: int | None = None,
    slug: str | None = None,
) -> list[dict[str, Any]]:
    pid = project_id
    if not pid and slug:
        project = store.get_production_project_by_slug(slug)
        pid = project.id if project else None
    if not pid:
        return []
    jobs = store.list_published_jobs_for_project(pid)
    links: list[dict[str, Any]] = []
    for job in jobs:
        account = store.get_publishing_account(job.account_id)
        links.append(
            {
                "job_id": job.id,
                "account_id": job.account_id,
                "platform": job.platform,
                "platform_url": job.platform_url,
                "platform_post_id": job.platform_post_id,
                "published_at": job.published_at,
                "account_display_name": account.display_name if account else None,
                "account_owner": account.owner if account else None,
                "account_username": account.username if account else None,
            }
        )
    return links
