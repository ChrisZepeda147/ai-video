#!/usr/bin/env python3
"""Cursor operator commands for pilot batches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from discovery.config import default_db_path, load_env
from discovery.pilot.batches import create_pilot_batch, get_pilot_results, run_pending_pilot_tasks
from discovery.pilot.preflight import run_preflight
from discovery.pilot.progress import refresh_item_progress
from discovery.store import DiscoveryStore


def cmd_preflight(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        report = run_preflight(store)
    print(json.dumps(report, indent=2))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        batch_id = create_pilot_batch(
            store,
            name=args.name,
            niche=args.niche,
            account_id=args.account,
            batch_size=args.size,
            use_first_batch_mix=not args.custom,
        )
        batch = store.get_pilot_batch(batch_id)
        items = store.list_pilot_batch_items(batch_id)
    print(f"Created pilot batch #{batch_id} ({batch.slug if batch else ''})")
    for item in items:
        print(f"  Item #{item.id} {item.slot_label}: {item.strategy} — {item.status}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        if args.batch:
            batches = [store.get_pilot_batch(args.batch)]
        else:
            batches = store.list_pilot_batches(limit=5)
        for batch in batches:
            if not batch:
                continue
            print(f"\nBatch #{batch.id} {batch.name} [{batch.status}] niche={batch.niche}")
            for item in store.list_pilot_batch_items(batch.id):
                refresh_item_progress(store, item.id)
                item = store.get_pilot_batch_item(item.id)
                if not item:
                    continue
                print(f"  #{item.id} {item.slot_label} ({item.strategy}) — {item.status}")
                if item.error_message:
                    print(f"    ERROR [{item.error_stage}]: {item.error_message}")
                import json as _json

                stages = _json.loads(item.stages_json or "{}")
                for stage, data in stages.items():
                    mark = data.get("status", "?")
                    if mark not in ("complete", "skipped"):
                        print(f"    {stage}: {mark} — {data.get('message', '')}")
    return 0


def cmd_run_pending(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        report = run_pending_pilot_tasks(
            store,
            batch_id=args.batch,
            limit=args.limit,
            live_publish=args.live,
        )
    print(f"Pilot run complete (batch={report.batch_id})")
    for task in report.tasks:
        print(f"  ✓ {task.action} item={task.item_id} entity={task.entity_id} — {task.message}")
    for msg in report.human_required:
        print(f"  ⏸ HUMAN: {msg}")
    for err in report.errors:
        print(f"  ✗ {err}", file=sys.stderr)
    return 0 if not report.errors else 1


def cmd_results(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        results = get_pilot_results(store, args.batch)
    print(json.dumps(results, indent=2))
    return 0


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Pilot batch operator")
    parser.add_argument("--db", type=Path, default=default_db_path())
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("preflight", help="System readiness checks")
    pf.set_defaults(func=cmd_preflight)

    create = sub.add_parser("create-batch", help="Create a pilot batch")
    create.add_argument("--name", default="First Pilot")
    create.add_argument("--niche", required=True)
    create.add_argument("--account", type=int, default=None)
    create.add_argument("--size", type=int, default=3)
    create.add_argument("--custom", action="store_true", help="Custom strategies instead of first-batch mix")
    create.set_defaults(func=cmd_create)

    status = sub.add_parser("pilot-status", help="Show pilot batch progress")
    status.add_argument("--batch", type=int, default=None)
    status.set_defaults(func=cmd_status)

    run = sub.add_parser("run-pending", help="Run safe pending pilot tasks")
    run.add_argument("--batch", type=int, default=None)
    run.add_argument("--limit", type=int, default=20)
    run.add_argument("--live", action="store_true", help="Allow live publish (still requires explicit publish)")
    run.set_defaults(func=cmd_run_pending)

    results = sub.add_parser("pilot-results", help="Pilot comparison results")
    results.add_argument("--batch", type=int, required=True)
    results.set_defaults(func=cmd_results)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
