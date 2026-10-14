#!/usr/bin/env python3
"""Run one direct-montage command job in an isolated process (weekly / detached worker)."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.command_montage import _kill_process_tree, run_direct_montage_command
from discovery.config import default_db_path, load_env, project_root, weekly_montage_job_timeout_sec
from discovery.store import DiscoveryStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _start_weekly_outer_watchdog(job_key: str) -> threading.Timer | None:
    """Last-resort kill if inner montage timeout does not return (pipe deadlock, etc.)."""
    store = DiscoveryStore(default_db_path())
    try:
        weekly = store._conn.execute(
            "SELECT id, slot, day FROM weekly_slots WHERE job_key = ? LIMIT 1",
            (job_key,),
        ).fetchone()
        if not weekly:
            return None
        slug = f"weekly-slot-{weekly['id']}"
    finally:
        store.close()

    grace_sec = 120
    limit = weekly_montage_job_timeout_sec() + grace_sec

    def _fire() -> None:
        db = DiscoveryStore(default_db_path())
        try:
            row = db._conn.execute(
                "SELECT status FROM cursor_command_jobs WHERE job_key = ?",
                (job_key,),
            ).fetchone()
            if not row or str(row["status"]) != "running":
                return
            msg = (
                f"Outer weekly watchdog: exceeded {limit}s wall clock. "
                "Killed worker process tree for retry."
            )
            print(
                f"WEEKLY_MONTAGE_TIMEOUT job_key={job_key} slug={slug} seconds={limit}",
                flush=True,
            )
            _kill_process_tree(os.getpid())
            db._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'failed', error_message = ?, completed_at = ?, worker_pid = NULL
                WHERE job_key = ?
                """,
                (msg, _now_iso(), job_key),
            )
            db._conn.commit()
            print(f"WEEKLY_MONTAGE_PROCESS_TREE_CLEARED job_key={job_key}", flush=True)
            try:
                from discovery.weekly import sync_weekly_slots_for_job

                sync_weekly_slots_for_job(db, job_key)
            except Exception:
                pass
        finally:
            db.close()
        os._exit(1)

    timer = threading.Timer(limit, _fire)
    timer.daemon = True
    timer.start()
    return timer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-key", required=True)
    args = parser.parse_args()
    os.environ["WEEKLY_MONTAGE_WORKER"] = "1"
    load_env()
    log_path = project_root() / "data" / "logs" / "weekly-montage-worker.log"
    watchdog = _start_weekly_outer_watchdog(args.job_key)
    try:
        run_direct_montage_command(job_key=args.job_key, block=True)
        return 0
    except Exception:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\nFATAL job {args.job_key}:\n")
            log.write(traceback.format_exc())
        return 1
    finally:
        if watchdog is not None:
            watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
