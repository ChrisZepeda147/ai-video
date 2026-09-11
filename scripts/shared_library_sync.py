#!/usr/bin/env python3
"""Shared library sync — Stephen + Chris export, push, pull, import."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery.config import default_db_path, load_env, project_root
from discovery.shared_library import (
    build_sync_health,
    export_owner,
    export_owner_existing,
    load_sync_state,
    now_iso,
    pull_and_import,
    save_sync_state,
    sync_health_path,
    sync_status,
    write_sync_health,
)
from discovery.brother_code_sync import brother_sync_interval_minutes, sync_source_code
from discovery.shared_library_git import commit_and_push
from discovery.store import DiscoveryStore

TASK_NAME = "AiVideoBrotherSync"


def _store():
    load_env()
    db = default_db_path()
    if not Path(db).is_file() and not Path(db).parent.exists():
        return None
    return DiscoveryStore(db)


def cmd_status(_args: argparse.Namespace) -> int:
    load_env()
    status = sync_status()
    print(json.dumps(status, indent=2))
    health = status.get("health") or {}
    print(health.get("summary") or "", file=sys.stderr)
    return 0 if health.get("ok") else 2


def cmd_health(_args: argparse.Namespace) -> int:
    load_env()
    status = sync_status()
    health = status.get("health") or build_sync_health(status)
    print(health.get("summary") or "")
    if _args.json:
        print(json.dumps({"health": health, "status": status}, indent=2, default=str))
    snapshot = sync_health_path()
    if snapshot.is_file():
        print(f"last timer write: {snapshot}", file=sys.stderr)
    return 0 if health.get("ok") else 2


def _watch_log_path() -> Path:
    return project_root() / "data" / "shared_library" / "watch.log"


def _append_watch_log(line: str) -> None:
    path = _watch_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{now_iso()}  {line}\n")
    if path.stat().st_size > 256_000:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_tick(_args: argparse.Namespace) -> int:
    """Pull/push source on both GitHubs, then import shared videos."""
    load_env()
    code = sync_source_code()
    store = _store()
    library: dict | None = None
    if store is not None:
        try:
            library = pull_and_import(store)
        finally:
            store.close()
    status = (library or {}).get("status") or sync_status(git=code.get("git"))
    if code.get("conflict") or code.get("step") == "rebase":
        git = dict(status.get("git") or {})
        git["conflict"] = True
        git["code_sync_hint"] = code.get("error") or "code conflict — fix then re-sync"
        status["git"] = git
        status["health"] = build_sync_health(status)
    write_sync_health(status)
    health = status.get("health") or build_sync_health(status)
    imported = int(((library or {}).get("import") or {}).get("imported") or 0)
    _append_watch_log(f"tick  imported={imported}  code_ok={code.get('ok')}  {health.get('summary')}")
    print(json.dumps({"ok": bool(code.get("ok")), "health": health, "code": code, "library": library}, indent=2, default=str))
    if not code.get("ok"):
        return 2
    if library and int((library.get("import") or {}).get("errors") or 0) > 0:
        return 1
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    minutes = max(1, int(args.minutes or brother_sync_interval_minutes()))
    print(f"brother sync watch every {minutes} min — Ctrl+C to stop")
    while True:
        cmd_tick(args)
        time.sleep(minutes * 60)


def _pythonw_path() -> Path:
    env_py = os.environ.get("AI_VIDEO_PYTHON", "").strip()
    candidates: list[Path] = []
    if env_py:
        candidates.append(Path(env_py))
    exe = Path(sys.executable)
    candidates.append(exe)
    local = Path.home() / "AppData" / "Local" / "Python" / "bin" / "python.exe"
    candidates.append(local)
    picked = next((path for path in candidates if path.is_file() and "WindowsApps" not in path.parts), exe)
    if picked.name.lower() == "pythonw.exe":
        return picked
    pythonw = picked.with_name("pythonw.exe")
    return pythonw if pythonw.is_file() else picked


def cmd_install(args: argparse.Namespace) -> int:
    load_env()
    minutes = max(1, int(args.minutes or brother_sync_interval_minutes()))
    script = Path(__file__).resolve()
    exe = _pythonw_path()
    tr = f'"{exe}" "{script}" tick'
    create = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/SC",
            "MINUTE",
            "/MO",
            str(minutes),
            "/RL",
            "LIMITED",
            "/F",
            "/TR",
            tr,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if create.returncode != 0:
        print(create.stderr.strip() or create.stdout.strip() or "schtasks create failed", file=sys.stderr)
        return 1
    print(f"installed {TASK_NAME} every {minutes} min")
    print(f"health file: {sync_health_path()}")
    if not args.skip_tick:
        return cmd_tick(args)
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        print(f"removed scheduled task: {TASK_NAME}")
        return 0
    print(result.stderr.strip() or "scheduled task not found")
    return 0


def cmd_export_existing(args: argparse.Namespace) -> int:
    store = _store()
    owner = args.owner or export_owner()
    if not owner:
        print("Set SHARED_LIBRARY_EXPORT_OWNER=stephen or chris in scripts/.env", file=sys.stderr)
        return 1
    try:
        result = export_owner_existing(store, owner=owner, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return 0 if not result.get("errors") else 1
    finally:
        if store:
            store.close()


def cmd_export_slug(args: argparse.Namespace) -> int:
    from discovery.config import project_root
    from discovery.shared_library import build_manifest_from_job, export_manifest_package

    owner = export_owner() or "stephen"
    manifest = build_manifest_from_job(args.slug, root=project_root(), owner=owner)
    if not manifest:
        print(f"No exportable job for slug: {args.slug}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    result = export_manifest_package(manifest)
    print(json.dumps(result, indent=2))
    return 0


def cmd_push_shared(args: argparse.Namespace) -> int:
    store = _store()
    owner = args.owner or export_owner()
    if not owner:
        print("Set SHARED_LIBRARY_EXPORT_OWNER=stephen or chris in scripts/.env", file=sys.stderr)
        return 1
    try:
        export_result = export_owner_existing(store, owner=owner, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps({"export": export_result}, indent=2, default=str))
            git_result = commit_and_push(f"shared library: sync {owner} packages", dry_run=True)
            print(json.dumps({"git": git_result}, indent=2))
            return 0

        message = args.message or f"shared library: {owner} sync ({export_result.get('exported', 0)} packages)"
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
        payload = pull_and_import(store, skip_pull=args.skip_pull, dry_run=args.dry_run)
        print(json.dumps(payload, indent=2, default=str))
        import_result = payload.get("import") or {}
        return 0 if import_result.get("errors", 0) == 0 else 1
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared library sync (Stephen + Chris)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show sync state summary")

    exp = sub.add_parser("export-existing", help="Export all local job/library videos for this machine's owner")
    exp.add_argument("--owner", help="stephen or chris (default: SHARED_LIBRARY_EXPORT_OWNER)")
    exp.add_argument("--dry-run", action="store_true")
    exp_legacy = sub.add_parser("export-stephen-existing", help="Alias for export-existing --owner stephen")
    exp_legacy.add_argument("--dry-run", action="store_true")

    slug = sub.add_parser("export-slug", help="Export one slug package")
    slug.add_argument("--slug", required=True)
    slug.add_argument("--dry-run", action="store_true")

    push = sub.add_parser("push-shared", help="Export unsynced packages, commit, push both remotes")
    push.add_argument("--owner", help="stephen or chris (default: SHARED_LIBRARY_EXPORT_OWNER)")
    push.add_argument("--dry-run", action="store_true")
    push.add_argument("--message", default="")
    push_legacy = sub.add_parser("push-stephen", help="Alias for push-shared --owner stephen")
    push_legacy.add_argument("--dry-run", action="store_true")
    push_legacy.add_argument("--message", default="")

    pull = sub.add_parser("pull-import", help="Pull Git shared_library and import Stephen + Chris packages")
    pull.add_argument("--dry-run", action="store_true")
    pull.add_argument("--skip-pull", action="store_true", help="Import local packages only (no git pull)")

    health = sub.add_parser("health", help="One-line synced / behind verdict")
    health.add_argument("--json", action="store_true")

    sub.add_parser("tick", help="Pull/push source on both GitHubs, then import videos")

    watch = sub.add_parser("watch", help="Loop source + video sync until stopped")
    watch.add_argument("--minutes", type=int, default=0, help="Interval minutes (default: env or 5)")

    install = sub.add_parser("install", help="Windows task: sync source + videos every N minutes")
    install.add_argument("--minutes", type=int, default=0, help="Interval minutes (default: env or 10)")
    install.add_argument("--skip-tick", action="store_true", help="Register task only, do not sync now")

    sub.add_parser("uninstall", help="Remove Windows brother-sync task")

    args = parser.parse_args()
    if args.command == "status":
        return cmd_status(args)
    if args.command == "health":
        return cmd_health(args)
    if args.command == "tick":
        return cmd_tick(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "install":
        return cmd_install(args)
    if args.command == "uninstall":
        return cmd_uninstall(args)
    if args.command == "export-existing":
        return cmd_export_existing(args)
    if args.command == "export-stephen-existing":
        args.owner = "stephen"
        return cmd_export_existing(args)
    if args.command == "export-slug":
        return cmd_export_slug(args)
    if args.command == "push-shared":
        return cmd_push_shared(args)
    if args.command == "push-stephen":
        args.owner = "stephen"
        return cmd_push_shared(args)
    if args.command == "pull-import":
        return cmd_pull_import(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
