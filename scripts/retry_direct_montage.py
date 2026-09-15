#!/usr/bin/env python3
"""Re-run a queued/failed/stuck montage command job without Cursor Agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.command_montage import run_direct_montage_command, should_use_direct_montage
from discovery.command_jobs import now_iso
from discovery.config import default_db_path, load_env
from discovery.store import DiscoveryStore


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_key", help="e.g. cmd_000011")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reset running/failed job to queued and start direct build",
    )
    args = parser.parse_args()

    store = DiscoveryStore(default_db_path())
    try:
        job = store._conn.execute(
            "SELECT job_key, user_command, status FROM cursor_command_jobs WHERE job_key = ?",
            (args.job_key,),
        ).fetchone()
        if not job:
            print(f"Job not found: {args.job_key}", file=sys.stderr)
            return 1
        user_command = str(job["user_command"] or "")
        if not should_use_direct_montage(user_command):
            print("Not a luxury-clips montage command.", file=sys.stderr)
            return 2
        status = str(job["status"] or "")
        if status == "running" and not args.force:
            print("Job is running. Pass --force to reset and run direct pipeline.", file=sys.stderr)
            return 3
        if args.force or status in {"running", "failed"}:
            store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'queued', started_at = NULL, completed_at = NULL,
                    error_message = NULL, stdout_log = NULL, stderr_log = NULL
                WHERE job_key = ?
                """,
                (args.job_key,),
            )
            store._conn.commit()
        run_direct_montage_command(job_key=args.job_key, user_command=user_command, block=True)
        print(f"Finished direct montage for {args.job_key} at {now_iso()}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
