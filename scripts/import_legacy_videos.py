#!/usr/bin/env python3
"""Import legacy rendered videos into production_projects for the site dashboard."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.config import project_root  # noqa: E402
from discovery.site_videos import default_db_path, import_videos_to_site  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402
from discovery.video_library import resolve_output_paths  # noqa: E402

import content_reuse  # noqa: E402


def sync_from_external(
    *,
    root: Path,
    external_root: Path,
    slugs: list[str] | None = None,
) -> list[dict]:
    catalog = content_reuse.load_persisted(root)
    copied: list[dict] = []
    for entry in catalog.videos:
        slug = str(entry.get("slug") or "")
        if slugs and slug not in slugs:
            continue
        for rel_path in resolve_output_paths(entry):
            src = external_root / rel_path
            dest = root / rel_path
            if not src.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dest)
            copied.append({"slug": slug, "path": rel_path})
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="Discovery SQLite path")
    parser.add_argument("--root", type=Path, default=project_root(), help="Repo root")
    parser.add_argument("--from-catalog", action="store_true", help="Import all videos listed in content/used.json")
    parser.add_argument("--slug", action="append", help="Import one catalog slug (repeatable)")
    parser.add_argument("--sync-from", type=Path, help="Copy legacy MP4s from another machine's repo root first")
    parser.add_argument("--copy", action="store_true", help="Copy files into downloads/production/{slug}/")
    parser.add_argument("--dry-run", action="store_true", help="Show what would import without writing SQLite")
    args = parser.parse_args()

    if args.sync_from:
        synced = sync_from_external(root=args.root, external_root=args.sync_from, slugs=args.slug)
        print(json.dumps({"synced": synced, "count": len(synced)}, indent=2))
        if not args.from_catalog and not args.slug:
            return 0 if synced else 1

    if not args.from_catalog and not args.slug:
        parser.error("Use --from-catalog, --slug, or --sync-from")

    store = DiscoveryStore(args.db or default_db_path(args.root))
    try:
        payload = import_videos_to_site(
            store,
            root=args.root,
            slugs=args.slug,
            rebuild_catalog=True,
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
    return 1 if missing and not args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
