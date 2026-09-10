#!/usr/bin/env python3
"""Stephen shared library sync — export, push, pull, import."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery.config import default_db_path, load_env
from discovery.shared_library import (
    export_stephen_after_register,
    export_stephen_existing,
    import_all_stephen_packages,
    load_sync_state,
    save_sync_state,
    sync_status,
)
from discovery.shared_library_git import commit_and_push, pull_shared_library
from discovery.store import DiscoveryStore


def _store():
    load_env()
    db = default_db_path()
    if not Path(db).is_file() and not Path(db).parent.exists():
        return None
    return DiscoveryStore(db)


def cmd_status(_args: argparse.Namespace) -> int:
    print(json.dumps(sync_status(), indent=2))
    return 0


def cmd_export_existing(args: argparse.Namespace) -> int:
    store = _store()
    try:
        result = export_stephen_existing(store, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return 0 if not result.get("errors") else 1
    finally:
        if store:
            store.close()


def cmd_export_slug(args: argparse.Namespace) -> int:
    from discovery.shared_library import build_manifest_from_job, export_manifest_package
    from discovery.config import project_root

    manifest = build_manifest_from_job(args.slug, root=project_root())
    if not manifest:
        print(f"No exportable job for slug: {args.slug}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    result = export_manifest_package(manifest)
    print(json.dumps(result, indent=2))
    return 0


def cmd_push_stephen(args: argparse.Namespace) -> int:
    store = _store()
    try:
        export_result = export_stephen_existing(store, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps({"export": export_result}, indent=2, default=str))
            git_result = commit_and_push("shared library: sync Stephen packages", dry_run=True)
            print(json.dumps({"git": git_result}, indent=2))
            return 0

        message = args.message or f"shared library: Stephen sync ({export_result.get('exported', 0)} packages)"
        git_result = commit_and_push(message, dry_run=False)
        if not git_result.get("ok"):
            print(json.dumps({"export": export_result, "git": git_result}, indent=2))
            return 2

        state = load_sync_state()
        from discovery.shared_library import now_iso

        state["last_push_at"] = now_iso()
        save_sync_state(state)

        print(json.dumps({"export": export_result, "git": git_result}, indent=2))
        return 0
    finally:
        if store:
            store.close()


def cmd_pull_import(args: argparse.Namespace) -> int:
    store = _store()
    if store is None:
        print("Discovery database not found — import requires local catalog.", file=sys.stderr)
        return 1
    try:
        pull_result = None
        pull_warning = None
        if not args.skip_pull:
            try:
                pull_result = pull_shared_library(dry_run=args.dry_run)
                if not pull_result.get("ok"):
                    pull_warning = pull_result.get("message")
                elif pull_result.get("warnings"):
                    pull_warning = "; ".join(str(w) for w in pull_result["warnings"])
                if not args.dry_run and pull_result and pull_result.get("ok"):
                    from discovery.shared_library import now_iso

                    state = load_sync_state()
                    state["last_pull_at"] = now_iso()
                    save_sync_state(state)
            except RuntimeError as exc:
                pull_warning = str(exc)

        import_result = import_all_stephen_packages(store, dry_run=args.dry_run)
        payload = {
            "pull_skipped": args.skip_pull,
            "pull_warning": pull_warning,
            "import": import_result,
        }
        if not args.skip_pull:
            payload["pull"] = pull_result
        print(json.dumps(payload, indent=2, default=str))
        return 0 if import_result.get("errors", 0) == 0 else 1
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stephen shared library sync")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show sync state summary")

    exp = sub.add_parser("export-stephen-existing", help="One-time export of all Stephen job outputs")
    exp.add_argument("--dry-run", action="store_true")

    slug = sub.add_parser("export-slug", help="Export one slug package")
    slug.add_argument("--slug", required=True)
    slug.add_argument("--dry-run", action="store_true")

    push = sub.add_parser("push-stephen", help="Export unsynced packages, commit, push (shared_library only)")
    push.add_argument("--dry-run", action="store_true")
    push.add_argument("--message", default="")

    pull = sub.add_parser("pull-import", help="Pull Git changes and import Stephen packages")
    pull.add_argument("--dry-run", action="store_true")
    pull.add_argument("--skip-pull", action="store_true", help="Import local packages only (no git pull)")

    args = parser.parse_args()
    if args.command == "status":
        return cmd_status(args)
    if args.command == "export-stephen-existing":
        return cmd_export_existing(args)
    if args.command == "export-slug":
        return cmd_export_slug(args)
    if args.command == "push-stephen":
        return cmd_push_stephen(args)
    if args.command == "pull-import":
        return cmd_pull_import(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
