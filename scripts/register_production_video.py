#!/usr/bin/env python3
"""Register a completed production video in the production content library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import default_db_path, load_env  # noqa: E402
from discovery.production_library import register_video  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--slug")
    parser.add_argument("--speaker")
    parser.add_argument("--podcast-source")
    parser.add_argument("--source-url")
    parser.add_argument("--source-platform")
    parser.add_argument("--source-id")
    parser.add_argument("--source-start", type=float)
    parser.add_argument("--source-end", type=float)
    parser.add_argument("--transcript")
    parser.add_argument("--topic")
    parser.add_argument("--hook")
    parser.add_argument("--tags")
    parser.add_argument("--creation-prompt")
    parser.add_argument("--final-path", required=True, help="Relative path to final MP4")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--parent-video-id", type=int)
    parser.add_argument("--version-label")
    parser.add_argument("--change-summary")
    parser.add_argument("--status", default="completed")
    parser.add_argument("--production-project-id", type=int)
    parser.add_argument("--component", action="append", default=[], help="JSON component object")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    components = []
    for raw in args.component:
        try:
            components.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            print(f"Invalid --component JSON: {exc}", file=sys.stderr)
            return 2

    tags = [part.strip() for part in (args.tags or "").split(",") if part.strip()] or None
    store = DiscoveryStore(args.db or default_db_path())
    try:
        video = register_video(
            store,
            title=args.title,
            slug=args.slug,
            speaker=args.speaker,
            podcast_source=args.podcast_source,
            source_url=args.source_url,
            source_platform=args.source_platform,
            source_external_id=args.source_id,
            source_start_sec=args.source_start,
            source_end_sec=args.source_end,
            transcript_segment=args.transcript,
            topic=args.topic,
            hook=args.hook,
            tags=tags,
            creation_prompt=args.creation_prompt,
            status=args.status,
            parent_video_id=args.parent_video_id,
            version_label=args.version_label,
            change_summary=args.change_summary,
            final_output_path=args.final_path,
            duration_sec=args.duration,
            production_project_id=args.production_project_id,
            components=components,
        )
    finally:
        store.close()

    print(json.dumps({"video_id": video["id"], "video_key": video["video_key"], "title": video["title"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
