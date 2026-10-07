#!/usr/bin/env python3
"""Validate Weekly slot retry (argv + run weekly path)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import default_db_path, load_env, project_root
from discovery.command_montage import parse_montage_command
from discovery.motivation_build import _build_command
from discovery.store import DiscoveryStore
from discovery.weekly import requeue_slot, run_weekly_retry_slot, slot_command_text


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    load_env()
    slot_id = int(sys.argv[1]) if len(sys.argv) > 1 else 28
    db = default_db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT s.*, p.week_start, p.owner
        FROM weekly_slots s JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.id = ?
        """,
        (slot_id,),
    ).fetchone()
    conn.close()
    if not row:
        print(f"Slot {slot_id} not found")
        return 1
    slot = dict(row)
    slot["image_paths"] = json.loads(slot.get("image_paths") or "[]")
    text = slot_command_text(slot)
    plan = parse_montage_command(text)
    if not plan:
        print("parse_montage_command failed")
        return 1
    cmd, slug, _rel = _build_command(plan, project_root())
    speaker_flag = None
    for i, tok in enumerate(cmd):
        if tok == "--speaker" and i + 1 < len(cmd):
            speaker_flag = cmd[i + 1]
        if tok == "--speech-url":
            print("ERROR: --speech-url present in argv")
            return 1
    min_s = next((cmd[i + 1] for i, t in enumerate(cmd) if t == "--min-seconds"), None)
    max_s = next((cmd[i + 1] for i, t in enumerate(cmd) if t == "--max-seconds"), None)
    print(f'WEEKLY_SLOT_SPEAKER="{slot.get("speaker")}"')
    print(f'DIRECT_ARGV_SPEAKER="{speaker_flag}"')
    print(f"MIN_SECONDS={min_s}")
    print(f"MAX_SECONDS={max_s}")
    print(f"SPEECH_URL_PINNED={1 if plan.get('speech_url') else 0}")
    print(f"SLUG={slug}")
    print("BROLL_QUERY=", plan.get("broll_query"))

    store = DiscoveryStore(db)
    try:
        st = str(slot.get("status") or "")
        if st == "failed":
            requeue_slot(store, slot_id)
        elif st not in {"queued", "failed"}:
            print(f"Slot status={st!r} — requeue may fail")
        print(f"Starting run_weekly_retry_slot({slot_id}) …")
        result = run_weekly_retry_slot(store, slot_id, wait_timeout_sec=14_400)
        print("BATCH_RESULT", json.dumps(result, indent=2, default=str))
        job_key = ""
        for item in result.get("submitted") or []:
            if str(item.get("slot_id")) == str(slot_id):
                job_key = str(item.get("job_key") or "")
        if job_key:
            job = store._conn.execute(
                "SELECT status, error_summary, stdout_log, production_video_id FROM cursor_command_jobs WHERE job_key=?",
                (job_key,),
            ).fetchone()
            if job:
                print(f"JOB_KEY={job_key}")
                print(f"JOB_STATUS={job['status']}")
                print(f"ERROR_SUMMARY={job['error_summary']}")
                print(f"PRODUCTION_VIDEO_ID={job['production_video_id']}")
                log = job["stdout_log"] or ""
                for pat in (
                    "Speech candidates:",
                    "Speech search fallback",
                    "Trying speech:",
                    "MONTAGE_SPEAKER",
                    "MONTAGE_SPEECH",
                    "MONTAGE_STAGE=ensure_broll",
                    "MONTAGE_TIMING stage=",
                    "MONTAGE_FAILURE=",
                ):
                    hits = [ln for ln in log.splitlines() if pat in ln]
                    if hits:
                        print(f"--- {pat} ---")
                        for ln in hits[-8:]:
                            print(ln)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
