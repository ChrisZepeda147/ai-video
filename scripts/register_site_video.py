#!/usr/bin/env python3
"""One-step: scan downloads + add rendered videos to the site library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import project_root  # noqa: E402
from discovery.site_videos import default_db_path, import_videos_to_site  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add rendered MP4s to the site (/videos). Run after any legacy pipeline render.",
    )
    parser.add_argument("--db", type=Path, default=None, help="Discovery SQLite path")
    parser.add_argument("--root", type=Path, default=project_root(), help="Repo root")
    parser.add_argument("--slug", action="append", help="Import one catalog slug (repeatable)")
    parser.add_argument("--no-rebuild", action="store_true", help="Skip content/used.json rescan")
    parser.add_argument("--copy", action="store_true", help="Copy files into downloads/production/{slug}/")
    parser.add_argument("--dry-run", action="store_true", help="Show ready imports without writing SQLite")
    args = parser.parse_args()

    db_path = args.db or default_db_path(args.root)
    store = DiscoveryStore(db_path)
    try:
        payload = import_videos_to_site(
            store,
            root=args.root,
            slugs=args.slug,
            rebuild_catalog=not args.no_rebuild,
            copy_files=args.copy,
            dry_run=args.dry_run,
        )
    finally:
        store.close()

    print(json.dumps(payload, indent=2))
    missing = [
        item for item in payload["results"]
        if item.get("status") == "skipped" and item.get("reason") == "missing_files"
    ]
    if missing and not args.dry_run:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
