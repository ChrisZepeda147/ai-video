#!/usr/bin/env python3
"""Production library queries for Cursor and operators."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import default_db_path, load_env  # noqa: E402
from discovery.production_library import check_reuse, get_video, list_videos  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="List production videos")
    list_p.add_argument("--limit", type=int, default=50)
    list_p.add_argument("--speaker")
    list_p.add_argument("--topic")

    show_p = sub.add_parser("show", help="Show one video with components")
    show_p.add_argument("--video-id", type=int, required=True)

    check_p = sub.add_parser("check-reuse", help="Look up prior production usage (advisory — does not block reuse)")
    check_p.add_argument("--source-url")
    check_p.add_argument("--source-id")
    check_p.add_argument("--source-platform")
    check_p.add_argument("--source-start", type=float)
    check_p.add_argument("--source-end", type=float)
    check_p.add_argument("--transcript")
    check_p.add_argument("--speaker")
    check_p.add_argument("--topic")
    check_p.add_argument("--video-id", type=int)
    check_p.add_argument("--hook")
    check_p.add_argument("--audio-path")

    args = parser.parse_args()
    store = DiscoveryStore(args.db or default_db_path())
    try:
        if args.cmd == "list":
            payload = list_videos(
                store,
                limit=args.limit,
                speaker=args.speaker,
                topic=args.topic,
            )
        elif args.cmd == "show":
            payload = get_video(store, args.video_id)
            if not payload:
                print(json.dumps({"error": "not found"}))
                return 1
        else:
            payload = check_reuse(
                store,
                source_url=args.source_url,
                source_external_id=args.source_id,
                source_platform=args.source_platform,
                source_start_sec=args.source_start,
                source_end_sec=args.source_end,
                transcript=args.transcript,
                speaker=args.speaker,
                topic=args.topic,
                hook=args.hook,
                audio_path=args.audio_path,
                video_id=args.video_id,
            )
        print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
