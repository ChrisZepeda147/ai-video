#!/usr/bin/env python3
"""E2E: retry one failed weekly slot through production path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from discovery.config import default_db_path, load_env, project_root
from discovery.montage_job_errors import command_job_error_summary
from discovery.store import DiscoveryStore
from discovery.weekly import run_weekly_retry_slot


def migration_status(store: DiscoveryStore) -> dict:
    rows = store._conn.execute("PRAGMA table_info(cursor_command_jobs)").fetchall()
    cols = {str(r["name"]) for r in rows}
    return {"error_summary_present": "error_summary" in cols, "columns": sorted(cols)}


def find_slot(store: DiscoveryStore, *, week_start: str, owner: str, day: str, slot: int):
    return store._conn.execute(
        """
        SELECT s.id, s.status, s.error_message, s.job_key, s.speaker, s.visual_direction, s.brief_text, s.slot
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND p.owner = ? AND s.day = ? AND s.slot = ?
        """,
        (week_start, owner, day, slot),
    ).fetchone()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-start", default="2026-10-05")
    parser.add_argument("--owner", default="chris")
    parser.add_argument("--day", default="tue")
    parser.add_argument("--slot", type=int, default=1)
    parser.add_argument("--wait-timeout-sec", type=int, default=7200)
    args = parser.parse_args()

    load_env()
    store = DiscoveryStore(default_db_path())
    try:
        mig = migration_status(store)
        print("MIGRATION", json.dumps(mig))
        row = find_slot(
            store,
            week_start=args.week_start,
            owner=args.owner,
            day=args.day,
            slot=args.slot,
        )
        if not row:
            print("Slot not found")
            return 2
        print("SLOT_BEFORE", json.dumps(dict(row), default=str))
        if str(row["status"]) not in {"failed", "queued"}:
            print(f"Slot status is {row['status']}; continuing retry anyway via requeue rules")
        result = run_weekly_retry_slot(
            store,
            int(row["id"]),
            wait_timeout_sec=args.wait_timeout_sec,
        )
        print("BATCH_RESULT", json.dumps(result, default=str))
        row2 = find_slot(
            store,
            week_start=args.week_start,
            owner=args.owner,
            day=args.day,
            slot=args.slot,
        )
        print("SLOT_AFTER", json.dumps(dict(row2), default=str))
        if row2 and row2["job_key"]:
            from discovery.command_jobs import get_command_job

            job = get_command_job(store, str(row2["job_key"]))
            if job:
                summary = command_job_error_summary(job)
                print("ERROR_SUMMARY", summary)
                tail = (job.get("stdout_log") or "")[-4000:]
                print("LOG_TAIL_START")
                print(tail)
                print("LOG_TAIL_END")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
