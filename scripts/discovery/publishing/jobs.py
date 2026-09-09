"""Publishing job lifecycle — schedule, publish, retry, idempotency."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import project_root, publish_dry_run
from discovery.publishing.credentials import load_credentials, save_credentials
from discovery.publishing.factory import build_publishing_provider
from discovery.publishing.base import PublishRequest

ACTIVE_JOB_STATUSES = {"draft", "scheduled", "queued", "publishing", "processing", "published"}
TERMINAL_FAIL = {"failed", "cancelled"}


@dataclass
class JobResult:
    job_id: int
    status: str
    platform_post_id: str | None = None
    platform_url: str | None = None
    error: str | None = None
    duplicate: bool = False


def _idempotency_key(production_project_id: int, account_id: int, scheduled_at: str | None) -> str:
    raw = f"{production_project_id}:{account_id}:{scheduled_at or 'now'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _require_approved_project(store, production_project_id: int):
    project = store.get_production_project(production_project_id)
    if not project:
        raise ValueError(f"Production project {production_project_id} not found")
    if project.status != "approved":
        raise ValueError(
            f"Only approved Shorts can be published (project status: {project.status})"
        )
    if not project.output_path or not Path(project.output_path).is_file():
        raise ValueError("Approved project has no rendered output file")
    return project


def create_publishing_jobs(
    store,
    *,
    production_project_id: int,
    account_ids: list[int],
    title: str | None = None,
    caption: str | None = None,
    hashtags: str | None = None,
    metadata_by_platform: dict[str, dict[str, Any]] | None = None,
    scheduled_at: str | None = None,
    timezone_name: str | None = None,
) -> list[JobResult]:
    project = _require_approved_project(store, production_project_id)
    results: list[JobResult] = []
    for account_id in account_ids:
        account = store.get_publishing_account(account_id)
        if not account or not account.enabled:
            raise ValueError(f"Account {account_id} not found or disabled")
        key = _idempotency_key(production_project_id, account_id, scheduled_at)
        existing = store.get_publishing_job_by_key(key)
        if existing and existing.status in ACTIVE_JOB_STATUSES:
            results.append(
                JobResult(
                    job_id=existing.id,
                    status=existing.status,
                    platform_post_id=existing.platform_post_id,
                    platform_url=existing.platform_url,
                    duplicate=True,
                )
            )
            continue
        meta = (metadata_by_platform or {}).get(account.platform, {})
        status = "scheduled" if scheduled_at else "draft"
        job_id = store.create_publishing_job(
            production_project_id=production_project_id,
            account_id=account_id,
            platform=account.platform,
            idempotency_key=key,
            title=title or project.title,
            caption=caption or project.hook_text,
            hashtags=hashtags,
            metadata_json=json.dumps(meta),
            scheduled_at=scheduled_at,
            timezone=timezone_name,
            status=status,
        )
        results.append(JobResult(job_id=job_id, status=status))
    return results


def create_test_publish_job(
    store,
    *,
    production_project_id: int,
    account_id: int,
    title: str | None = None,
    caption: str | None = None,
) -> JobResult:
    """Create a private test upload job — requires explicit live publish."""
    account = store.get_publishing_account(account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")
    meta = {"privacy_status": "private", "test_upload": True}
    jobs = create_publishing_jobs(
        store,
        production_project_id=production_project_id,
        account_ids=[account_id],
        title=title,
        caption=caption,
        metadata_by_platform={account.platform: meta},
    )
    if not jobs:
        raise ValueError("Failed to create test publish job")
    return jobs[0]


def publish_test_upload(store, job_id: int, *, live: bool = False) -> JobResult:
    if not live:
        raise ValueError(
            "Test upload requires live=True. Uploads use private visibility — never auto-live."
        )
    return publish_job(store, job_id, live=True)


def publish_job(store, job_id: int, *, force: bool = False, live: bool = False) -> JobResult:
    job = store.get_publishing_job(job_id)
    if not job:
        raise ValueError(f"Publishing job {job_id} not found")
    if job.status == "published" and not force:
        return JobResult(
            job_id=job_id,
            status=job.status,
            platform_post_id=job.platform_post_id,
            platform_url=job.platform_url,
            duplicate=True,
        )
    if job.status in {"publishing", "processing"}:
        return JobResult(job_id=job_id, status=job.status, duplicate=True)

    project = _require_approved_project(store, job.production_project_id)
    account = store.get_publishing_account(job.account_id)
    if not account:
        raise ValueError(f"Account {job.account_id} not found")

    claimed = store.claim_publishing_job(job_id, from_statuses=("draft", "scheduled", "queued", "failed"))
    if not claimed:
        refreshed = store.get_publishing_job(job_id)
        return JobResult(
            job_id=job_id,
            status=refreshed.status if refreshed else job.status,
            duplicate=True,
        )

    store.increment_publishing_job_attempts(job_id)
    provider = build_publishing_provider(account.platform)
    creds = load_credentials(account.id)
    try:
        if publish_dry_run() and not live:
            from discovery.publishing.mock import MockPublishingProvider

            provider = MockPublishingProvider(account.platform)
        else:
            creds = provider.refresh_credentials(creds)
            save_credentials(account.id, creds)
    except Exception:
        pass

    video_path = project.output_path
    if not video_path.startswith(str(project_root())):
        video_path = str(Path(video_path))
    meta = {}
    if job.metadata_json:
        try:
            meta = json.loads(job.metadata_json)
        except json.JSONDecodeError:
            meta = {}

    try:
        result = provider.publish_video(
            creds,
            PublishRequest(
                video_path=video_path,
                title=job.title or project.title,
                caption=job.caption or "",
                hashtags=job.hashtags or "",
                metadata=meta,
            ),
        )
        store.complete_publishing_job(
            job_id,
            status="published" if result.status == "published" else "processing",
            platform_post_id=result.platform_post_id,
            platform_url=result.platform_url,
        )
        store.record_project_published(
            job.production_project_id,
            account_id=job.account_id,
            platform=job.platform,
            platform_url=result.platform_url,
        )
        return JobResult(
            job_id=job_id,
            status=result.status,
            platform_post_id=result.platform_post_id,
            platform_url=result.platform_url,
        )
    except Exception as exc:
        store.fail_publishing_job(job_id, str(exc))
        raise


def cancel_publishing_job(store, job_id: int) -> JobResult:
    job = store.get_publishing_job(job_id)
    if not job:
        raise ValueError(f"Publishing job {job_id} not found")
    if job.status not in {"draft", "scheduled", "queued"}:
        raise ValueError(f"Cannot cancel job in status {job.status}")
    store.update_publishing_job_status(job_id, "cancelled")
    return JobResult(job_id=job_id, status="cancelled")


def retry_publishing_job(store, job_id: int) -> JobResult:
    job = store.get_publishing_job(job_id)
    if not job:
        raise ValueError(f"Publishing job {job_id} not found")
    if job.status != "failed":
        raise ValueError(f"Only failed jobs can be retried (status: {job.status})")
    store.update_publishing_job_status(job_id, "queued")
    return publish_job(store, job_id)


def publish_due_jobs(store, *, limit: int = 20) -> list[JobResult]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    due = store.list_due_publishing_jobs(before_iso=now, limit=limit)
    results: list[JobResult] = []
    for job in due:
        store.update_publishing_job_status(job.id, "queued")
        try:
            results.append(publish_job(store, job.id))
        except Exception as exc:
            results.append(JobResult(job_id=job.id, status="failed", error=str(exc)))
    return results
