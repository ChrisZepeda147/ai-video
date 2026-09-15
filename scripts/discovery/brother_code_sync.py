"""Brother code + shared library sync while the API is running."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from discovery.shared_library import (
    export_enabled,
    import_all_shared_packages,
    load_sync_state,
    now_iso,
    pull_and_import,
    save_sync_state,
    sync_visual_packs,
)
from discovery.shared_library_git import git_repo_status, safe_ff_pull


def auto_pull_enabled() -> bool:
    return os.environ.get("BROTHER_AUTO_PULL", "1").strip().lower() not in ("0", "false", "no")


def brother_sync_interval_minutes() -> int:
    """Unified interval for brother video + code sync (default 10 min)."""
    for key in ("BROTHER_SYNC_MINUTES", "BROTHER_AUTO_PULL_MINUTES", "SHARED_LIBRARY_AUTO_SYNC_MINUTES"):
        raw = os.environ.get(key, "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                break
    return 10


def auto_pull_interval_minutes() -> int:
    return brother_sync_interval_minutes()


def _sync_is_due(state: dict[str, Any], *, interval_minutes: int | None = None) -> bool:
    interval = interval_minutes if interval_minutes is not None else brother_sync_interval_minutes()
    last = state.get("last_brother_sync_at") or state.get("last_auto_sync_at") or state.get("last_code_pull_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return elapsed >= interval * 60
    except ValueError:
        return True


def sync_source_code() -> dict[str, Any]:
    """Fetch remotes and fast-forward pull when the working tree is clean."""
    from discovery.shared_library_git import PUSH_REMOTES, _run_git

    fetch_errors: list[str] = []
    for remote in PUSH_REMOTES:
        fetch = _run_git(["fetch", remote], check=False)
        if fetch.returncode != 0:
            fetch_errors.append(f"{remote}: {(fetch.stderr or fetch.stdout or '').strip()}")

    pull_result = safe_ff_pull()
    git_status = git_repo_status(fetch=False)
    ok = bool(pull_result.get("ok", True)) and not git_status.get("conflict")
    if pull_result.get("skipped") and int(git_status.get("commits_behind") or 0) > 0:
        ok = False
    return {
        "ok": ok,
        "fetch_errors": fetch_errors,
        "pull": pull_result,
        "git": git_status,
        "step": pull_result.get("step"),
        "conflict": bool(git_status.get("conflict") or pull_result.get("conflict")),
        "error": pull_result.get("error") or pull_result.get("message"),
    }


def run_brother_sync_tick(store, *, force: bool = False) -> dict[str, Any] | None:
    """One tick: shared library pull + deletions + import, then code pull."""
    if not force and not auto_pull_enabled():
        return None
    state = load_sync_state()
    if not force and not _sync_is_due(state):
        return None

    library = pull_and_import(store, fetch_git=not force)
    code = sync_source_code()

    if code.get("pull", {}).get("pulled") and not export_enabled():
        import_result = import_all_shared_packages(store)
        if int(import_result.get("imported") or 0) > 0:
            sync_visual_packs(store)
        library["post_code_import"] = import_result

    state = load_sync_state()
    ts = now_iso()
    state["last_brother_sync_at"] = ts
    state["last_auto_sync_at"] = ts
    state["last_code_pull_at"] = ts
    save_sync_state(state)

    return {
        "brother_sync": True,
        "skipped": False,
        "library": library,
        "code": code,
        "git": code.get("git") or library.get("git"),
    }


def maybe_auto_brother_code_pull(store, *, force: bool = False) -> dict[str, Any] | None:
    return run_brother_sync_tick(store, force=force)


def maybe_auto_pull_import_unified(store, *, force: bool = False) -> dict[str, Any] | None:
    """Alias used by API — same as brother sync tick."""
    return run_brother_sync_tick(store, force=force)


def _pull_is_due(state: dict[str, Any], *, interval_minutes: int | None = None) -> bool:
    return _sync_is_due(state, interval_minutes=interval_minutes)


def run_session_start_sync(store) -> dict[str, Any]:
    """Agent/session start: full brother sync now."""
    return run_brother_sync_tick(store, force=True) or {
        "brother_sync": True,
        "skipped": True,
        "reason": "disabled",
    }
