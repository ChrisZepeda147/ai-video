#!/usr/bin/env python3
"""Combination Board operator helpers for Cursor and CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.combination_render import render_combination  # noqa: E402
from discovery.combinations import (  # noqa: E402
    catalog_payload,
    combination_status,
    import_usage_from_videos,
    list_audio_catalog,
    list_visual_packs,
    query_unused_combinations,
    sync_visual_packs,
)
from discovery.config import default_db_path, load_env  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync-catalog", help="Refresh visual packs from library")

    cat = sub.add_parser("catalog", help="Show audio + visual catalog")
    cat.add_argument("--owner")

    status_p = sub.add_parser("status", help="Pairing status for one audio clip")
    status_p.add_argument("--owner", required=True)
    status_p.add_argument("--audio-id", type=int, required=True)

    unused_p = sub.add_parser("unused", help="List unused pairings for owner/speaker")
    unused_p.add_argument("--owner", required=True)
    unused_p.add_argument("--speaker")

    render_p = sub.add_parser("render", help="Render audio + visual pack combination")
    render_p.add_argument("--owner", required=True)
    render_p.add_argument("--audio-id", type=int, required=True)
    render_p.add_argument("--pack-id", type=int, required=True)
    render_p.add_argument("--audio-start", type=float)
    render_p.add_argument("--audio-end", type=float)
    render_p.add_argument("--version-label")
    render_p.add_argument("--force", action="store_true")

    imp = sub.add_parser("import-usage", help="Backfill pairing usage from existing videos")
    imp.add_argument("--owner", required=True)
    imp.add_argument("--all", action="store_true")
    imp.add_argument("--video-id", type=int, action="append", default=[])
    imp.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    store = DiscoveryStore(args.db or default_db_path())
    try:
        if args.cmd == "sync-catalog":
            payload = sync_visual_packs(store)
            print(json.dumps({"synced": len(payload)}, indent=2))
        elif args.cmd == "catalog":
            print(json.dumps(catalog_payload(store, owner=args.owner), indent=2, default=str))
        elif args.cmd == "status":
            print(json.dumps(combination_status(store, owner=args.owner, audio_component_id=args.audio_id), indent=2, default=str))
        elif args.cmd == "unused":
            print(json.dumps(query_unused_combinations(store, owner=args.owner, speaker=args.speaker), indent=2, default=str))
        elif args.cmd == "render":
            result = render_combination(
                store,
                owner=args.owner,
                audio_component_id=args.audio_id,
                visual_pack_id=args.pack_id,
                audio_start_sec=args.audio_start,
                audio_end_sec=args.audio_end,
                version_label=args.version_label,
                force_usage=args.force,
            )
            print(json.dumps({"video_id": result["video"]["id"], "output_path": result["output_path"]}, indent=2))
        elif args.cmd == "import-usage":
            print(
                json.dumps(
                    import_usage_from_videos(
                        store,
                        owner=args.owner,
                        video_ids=args.video_id or None,
                        all_videos=args.all,
                        dry_run=args.dry_run,
                    ),
                    indent=2,
                    default=str,
                )
            )
        else:
            print(json.dumps({"audio": list_audio_catalog(store), "packs": list_visual_packs(store)}, indent=2, default=str))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
