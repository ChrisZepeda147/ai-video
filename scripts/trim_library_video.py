#!/usr/bin/env python3
"""Trim a production library final MP4 — override in place or save as new version."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import default_db_path, load_env
from discovery.library_trim import trim_library_video
from discovery.store import DiscoveryStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Trim a production library video final MP4.")
    parser.add_argument("--video-id", type=int, required=True)
    parser.add_argument("--start-sec", type=float, required=True)
    parser.add_argument("--end-sec", type=float, required=True)
    parser.add_argument(
        "--mode",
        choices=("override", "new_version"),
        default="new_version",
        help="Replace this library row's final.mp4 or register a child version",
    )
    parser.add_argument("--change-summary", default=None)
    parser.add_argument("--version-label", default=None)
    args = parser.parse_args()

    load_env()
    store = DiscoveryStore(default_db_path())
    try:
        result = trim_library_video(
            store,
            args.video_id,
            start_sec=args.start_sec,
            end_sec=args.end_sec,
            mode=args.mode,
            change_summary=args.change_summary,
            version_label=args.version_label,
        )
    finally:
        store.close()

    print(f"OK video_id={result.get('id')} duration_sec={result.get('duration_sec')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
