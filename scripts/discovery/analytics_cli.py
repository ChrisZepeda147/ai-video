#!/usr/bin/env python3
"""Cursor operator commands for post-publish analytics."""

from __future__ import annotations

import argparse
import json
import sys

from discovery.analytics.discovery_feedback import compute_internal_fit
from discovery.analytics.patterns import (
    aggregate_formats,
    aggregate_hooks,
    aggregate_topics,
    aggregate_visuals,
    compare_format_profiles,
)
from discovery.analytics.profiles import build_performance_profile
from discovery.analytics.refresh import analytics_status, refresh_analytics
from discovery.config import default_db_path, load_env
from discovery.store import DiscoveryStore


def cmd_refresh(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        results = refresh_analytics(
            store,
            account_id=args.account,
            job_id=args.post,
            limit=args.limit,
            force=args.force,
        )
        for result in results:
            if result.refreshed:
                print(f"Job #{result.job_id}: snapshot #{result.snapshot_id}")
            elif result.error:
                print(f"Job #{result.job_id}: ERROR {result.error}", file=sys.stderr)
            else:
                print(f"Job #{result.job_id}: skipped ({result.skipped_reason})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        print(json.dumps(analytics_status(store), indent=2))
    return 0


def cmd_hooks(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = store.list_analytics_posts_with_latest(niche=args.niche, limit=args.limit)
        print(json.dumps(aggregate_hooks(rows), indent=2))
    return 0


def cmd_visuals(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = store.list_analytics_posts_with_latest(niche=args.niche, limit=args.limit)
        print(json.dumps(aggregate_visuals(rows), indent=2))
    return 0


def cmd_breakouts(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = [
            r
            for r in store.list_latest_post_snapshots(limit=args.limit)
            if r.get("performance_tier") == "breakout"
        ]
        print(json.dumps(rows, indent=2))
    return 0


def cmd_compare_formats(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = store.list_analytics_posts_with_latest(niche=args.niche, limit=args.limit)
        print(json.dumps(compare_format_profiles(rows), indent=2))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        profile = build_performance_profile(
            store,
            niche=args.niche,
            account_id=args.account,
            lookback=args.limit,
        )
        print(json.dumps(profile, indent=2))
    return 0


def cmd_internal_fit(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        fit = compute_internal_fit(store, reference_id=args.reference, niche=args.niche)
        print(json.dumps(fit, indent=2))
    return 0


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Analytics operator commands")
    parser.add_argument("--db", type=default_db_path.__class__, default=default_db_path())
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("analytics-refresh", help="Refresh post analytics snapshots")
    refresh.add_argument("--account", type=int, default=None)
    refresh.add_argument("--post", type=int, default=None, help="Publishing job id")
    refresh.add_argument("--limit", type=int, default=50)
    refresh.add_argument("--force", action="store_true")
    refresh.set_defaults(func=cmd_refresh)

    status = sub.add_parser("analytics-status", help="Show analytics refresh status")
    status.set_defaults(func=cmd_status)

    hooks = sub.add_parser("analytics-hooks", help="Show winning hook formulas")
    hooks.add_argument("--niche", default=None)
    hooks.add_argument("--limit", type=int, default=50)
    hooks.set_defaults(func=cmd_hooks)

    visuals = sub.add_parser("analytics-visuals", help="Show winning visual styles")
    visuals.add_argument("--niche", default=None)
    visuals.add_argument("--limit", type=int, default=50)
    visuals.set_defaults(func=cmd_visuals)

    breakouts = sub.add_parser("analytics-breakouts", help="List breakout Shorts")
    breakouts.add_argument("--limit", type=int, default=10)
    breakouts.set_defaults(func=cmd_breakouts)

    compare = sub.add_parser("analytics-compare-formats", help="Compare source-audio vs source-video")
    compare.add_argument("--niche", default=None)
    compare.add_argument("--limit", type=int, default=50)
    compare.set_defaults(func=cmd_compare_formats)

    profile = sub.add_parser("analytics-profile", help="Build/update performance profile")
    profile.add_argument("--niche", required=True)
    profile.add_argument("--account", type=int, default=None)
    profile.add_argument("--limit", type=int, default=30)
    profile.set_defaults(func=cmd_profile)

    fit = sub.add_parser("analytics-internal-fit", help="Internal fit for a reference")
    fit.add_argument("--reference", type=int, required=True)
    fit.add_argument("--niche", default=None)
    fit.set_defaults(func=cmd_internal_fit)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
