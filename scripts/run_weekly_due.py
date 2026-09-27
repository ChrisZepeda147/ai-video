#!/usr/bin/env python3
"""Run due weekly slots for a calendar day (7am worker).

Default morning install: submit all 3 due slots at 7am (--morning-batch).
Use --parallel or --serial for other behavior.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import default_db_path, load_env
from discovery.store import DiscoveryStore
from discovery.weekly import (
    VIDEOS_PER_DAY,
    normalize_owner,
    run_weekly_due_batch,
    weekly_agent_model,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit due weekly slots to Cursor.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--owner", default=None, help="chris | stephen (default: both)")
    parser.add_argument(
        "--limit",
        type=int,
        default=VIDEOS_PER_DAY,
        help="Max slots to submit this run (default: 3 per owner day)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List due slots only")
    parser.add_argument(
        "--morning-batch",
        action="store_true",
        help="7am mode: submit up to --limit due slots at once (default if neither serial nor parallel set)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Submit up to --limit slots in one run without waiting between agents",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Submit at most one slot per run",
    )
    parser.add_argument(
        "--wait-complete",
        action="store_true",
        help="Block until up to --limit slots finish (long run)",
    )
    parser.add_argument("--wait-timeout-minutes", type=int, default=240, help="With --wait-complete")
    parser.add_argument("--retry-failed", action="store_true", help="Re-queue failed slots for today first")
    args = parser.parse_args()

    if args.serial and args.parallel:
        print("Use only one of --serial or --parallel / --morning-batch")
        return 2

    morning = args.morning_batch or (args.parallel and not args.serial)
    if not args.serial and not args.parallel and not args.wait_complete:
        morning = True

    serial = args.serial or (not morning and not args.wait_complete)

    day = args.date or date.today().isoformat()
    owner = normalize_owner(args.owner) if args.owner else None

    load_env()
    store = DiscoveryStore(default_db_path())
    try:
        result = run_weekly_due_batch(
            store,
            day=day,
            owner=owner,
            limit=args.limit,
            dry_run=args.dry_run,
            serial=serial,
            wait_complete=args.wait_complete,
            wait_timeout_sec=max(60, args.wait_timeout_minutes * 60),
            retry_failed=args.retry_failed,
        )
    finally:
        store.close()

    if result.get("error"):
        print(f"Preflight failed: {result['error']}")
        return 2

    if result.get("dry_run"):
        print(f"Due weekly slots for {day}: {result.get('due_count', 0)}")
        for slot in result.get("due") or []:
            print(
                f"  - {slot['owner']} {slot['day']}#{slot['slot']}: "
                f"{slot['speaker']} / {slot['visual_direction']}"
            )
        return 0

    rec = result.get("reconcile") or {}
    if rec.get("reconciled_done") or rec.get("reconciled_failed"):
        print(f"Reconciled: {rec}")

    if result.get("deferred"):
        print(f"Deferred ({result.get('reason', 'busy')}): job already running for {day}")
        return 0

    if result.get("count", 0) == 0:
        print(f"No due weekly slots for {day} (owner={owner or 'all'})")
        return 0

    mode = "morning batch" if morning else ("serial" if serial else "parallel")
    print(f"Agent model: {result.get('agent_model') or weekly_agent_model()} ({mode}, n={result.get('count')})")
    for item in result.get("submitted") or []:
        print(f"  submitted {item['slot_id']} -> {item['job_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
