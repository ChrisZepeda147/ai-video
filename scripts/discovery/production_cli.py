#!/usr/bin/env python3
"""Cursor operator commands for production pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from discovery.config import default_db_path, load_env
from discovery.generation_jobs import import_generation_job, list_pending_generation_jobs
from discovery.production_projects import (
    build_project_timeline,
    render_project,
    transcribe_source,
)
from discovery.acquire import acquire_source_media, clip_source_segment
from discovery.store import DiscoveryStore


def cmd_acquire_pending(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = store._conn.execute(
            """
            SELECT id FROM source_media
            WHERE download_status IS NULL OR download_status IN ('pending', 'failed')
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        for row in rows:
            sid = int(row["id"])
            try:
                result = acquire_source_media(store, sid)
                print(f"Acquired source #{sid}: {result.download_path}")
            except Exception as exc:
                print(f"Failed source #{sid}: {exc}", file=sys.stderr)
    return 0


def cmd_transcribe_pending(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = store._conn.execute(
            """
            SELECT id FROM source_media
            WHERE download_status = 'acquired' AND (transcript IS NULL OR transcript LIKE '[transcript pending%')
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        for row in rows:
            sid = int(row["id"])
            try:
                transcribe_source(store, sid)
                print(f"Transcribed source #{sid}")
            except Exception as exc:
                print(f"Failed source #{sid}: {exc}", file=sys.stderr)
    return 0


def cmd_import_jobs(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        jobs = list_pending_generation_jobs(store, limit=args.limit)
        for job in jobs:
            try:
                result = import_generation_job(store, job.id)
                print(f"Job {job.job_key}: imported={result['imported']} skipped={result['skipped']}")
            except Exception as exc:
                print(f"Job {job.job_key} failed: {exc}", file=sys.stderr)
    return 0


def cmd_build_timelines(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        projects = store.list_production_projects(status="draft", limit=args.limit)
        for project in projects:
            try:
                build_project_timeline(store, project.id)
                print(f"Timeline ready: project #{project.id} {project.slug}")
            except Exception as exc:
                print(f"Project #{project.id} failed: {exc}", file=sys.stderr)
    return 0


def cmd_render_ready(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        projects = store.list_production_projects(status="ready", limit=args.limit)
        for project in projects:
            try:
                result = render_project(store, project.id)
                print(f"Rendered project #{project.id}: {result.output_path}")
            except Exception as exc:
                print(f"Project #{project.id} failed: {exc}", file=sys.stderr)
    return 0


def cmd_project_status(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        project = store.get_production_project(args.project_id)
        if not project:
            print(f"Project {args.project_id} not found", file=sys.stderr)
            return 1
        print(f"Project #{project.id} {project.slug}")
        print(f"  status: {project.status}")
        print(f"  output: {project.output_path}")
        print(f"  error:  {project.error_message}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    load_env()
    parser = argparse.ArgumentParser(description="Production operator CLI")
    parser.add_argument("--db", type=Path, default=default_db_path())
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("acquire-pending", help="Download pending source media")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_acquire_pending)

    p = sub.add_parser("transcribe-pending", help="Transcribe acquired sources")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_transcribe_pending)

    p = sub.add_parser("import-jobs", help="Import completed generation jobs")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_import_jobs)

    p = sub.add_parser("build-timelines", help="Build timelines for draft projects")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_build_timelines)

    p = sub.add_parser("render-ready", help="Render ready production projects")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_render_ready)

    p = sub.add_parser("project-status", help="Inspect a project failure")
    p.add_argument("project_id", type=int)
    p.set_defaults(func=cmd_project_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
