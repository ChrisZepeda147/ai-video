#!/usr/bin/env python3
"""Cursor operator commands for social publishing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from discovery.config import default_db_path, load_env
from discovery.publishing.accounts import import_mock_account, verify_publishing_account
from discovery.publishing.jobs import (
    cancel_publishing_job,
    create_publishing_jobs,
    publish_due_jobs,
    publish_job,
    retry_publishing_job,
)
from discovery.store import DiscoveryStore


def cmd_publish_due(args: argparse.Namespace) -> int:
    os.environ.setdefault("DISCOVERY_PUBLISH_DRY_RUN", "1")
    with DiscoveryStore(args.db) as store:
        results = publish_due_jobs(store, limit=args.limit)
        for result in results:
            print(f"Job #{result.job_id}: {result.status} {result.platform_url or result.error or ''}")
    return 0


def cmd_publish_job(args: argparse.Namespace) -> int:
    if not args.live:
        os.environ["DISCOVERY_PUBLISH_DRY_RUN"] = "1"
    with DiscoveryStore(args.db) as store:
        result = publish_job(store, args.job_id)
        print(json.dumps(result.__dict__, indent=2))
    return 0 if result.status in {"published", "processing"} else 1


def cmd_retry_failed(args: argparse.Namespace) -> int:
    os.environ.setdefault("DISCOVERY_PUBLISH_DRY_RUN", "1")
    with DiscoveryStore(args.db) as store:
        jobs = store.list_publishing_jobs(status="failed", limit=args.limit)
        for job in jobs:
            try:
                result = retry_publishing_job(store, job.id)
                print(f"Retried #{job.id}: {result.status}")
            except Exception as exc:
                print(f"Retry failed #{job.id}: {exc}", file=sys.stderr)
    return 0


def cmd_schedule_status(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        for status in ("scheduled", "queued", "publishing", "processing", "published", "failed"):
            jobs = store.list_publishing_jobs(status=status, limit=50)
            if jobs:
                print(f"\n{status.upper()} ({len(jobs)})")
                for job in jobs:
                    print(
                        f"  #{job.id} project={job.production_project_id} "
                        f"account={job.account_id} platform={job.platform} "
                        f"scheduled={job.scheduled_at or '-'} "
                        f"error={job.error_message or '-'}"
                    )
    return 0


def cmd_job_status(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        job = store.get_publishing_job(args.job_id)
        if not job:
            print(f"Job {args.job_id} not found", file=sys.stderr)
            return 1
        print(json.dumps(job.__dict__, indent=2, default=str))
    return 0


def cmd_add_mock_account(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        account_id = import_mock_account(
            store,
            platform=args.platform,
            display_name=args.name,
            username=args.username or args.name,
            niche=args.niche,
        )
        verify_publishing_account(store, account_id)
        print(f"Mock account #{account_id} ({args.platform}) created")
    return 0


def build_parser() -> argparse.ArgumentParser:
    load_env()
    parser = argparse.ArgumentParser(description="Publishing operator CLI")
    parser.add_argument("--db", type=Path, default=default_db_path())
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("publish-due", help="Publish scheduled jobs that are due")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_publish_due)

    p = sub.add_parser("publish-job", help="Publish a specific job")
    p.add_argument("job_id", type=int)
    p.add_argument("--live", action="store_true", help="Actually publish (default dry-run)")
    p.set_defaults(func=cmd_publish_job)

    p = sub.add_parser("retry-failed", help="Retry failed publishing jobs")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_retry_failed)

    p = sub.add_parser("schedule-status", help="Show publishing queue status")
    p.set_defaults(func=cmd_schedule_status)

    p = sub.add_parser("job-status", help="Inspect a publishing job")
    p.add_argument("job_id", type=int)
    p.set_defaults(func=cmd_job_status)

    p = sub.add_parser("add-mock-account", help="Create mock connected account for dev/tests")
    p.add_argument("platform", choices=["youtube", "tiktok", "instagram", "facebook"])
    p.add_argument("name", help="Display name")
    p.add_argument("--username")
    p.add_argument("--niche")
    p.set_defaults(func=cmd_add_mock_account)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
