#!/usr/bin/env python3
"""Submit a daily 3-video brief to the command center (one agent session)."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.command_jobs import submit_command
from discovery.config import default_db_path, load_env
from discovery.driven_visuals import batch_dir, parse_daily_video_briefs, write_batch_manifest
from discovery.store import DiscoveryStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a DrivenVisuals daily batch brief.")
    parser.add_argument("--brief-file", type=Path, required=True, help="Markdown/text file with VIDEO 1/2/3 blocks")
    parser.add_argument("--date", default=None, help="Batch date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Parse brief and write manifest only")
    args = parser.parse_args()

    if not args.brief_file.is_file():
        print(f"Brief file not found: {args.brief_file}", file=sys.stderr)
        return 2

    brief_text = args.brief_file.read_text(encoding="utf-8")
    briefs = parse_daily_video_briefs(brief_text)
    if not briefs:
        print("No VIDEO 1/2/3 blocks found in brief.", file=sys.stderr)
        return 2

    batch_day = date.fromisoformat(args.date) if args.date else None
    folder = batch_dir(batch_day)
    brief_copy = folder / "brief.md"
    brief_copy.write_text(brief_text, encoding="utf-8")
    manifest = write_batch_manifest(briefs=briefs, batch_date=batch_day, source_command=brief_text)
    print(f"Batch folder: {folder}")
    print(f"Manifest: {manifest}")
    print(f"Videos: {len(briefs)}")

    if args.dry_run:
        return 0

    load_env()
    store = DiscoveryStore(default_db_path())
    try:
        command = (
            f"Daily batch {folder.name} — produce all {len(briefs)} videos sequentially.\n\n"
            f"{brief_text.strip()}"
        )
        result = submit_command(store, user_command=command, batch_count=len(briefs))
    finally:
        store.close()

    if result.get("batch"):
        print(f"Submitted batch jobs: {result.get('batch_count')}")
        for job in result.get("jobs") or []:
            print(f"  - {job.get('job_key')} -> {job.get('poll_url')}")
    else:
        print(f"Submitted job: {result.get('job_key')} -> {result.get('poll_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
