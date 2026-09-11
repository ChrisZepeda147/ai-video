"""Auto git pull for brother code sync while the API is running."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from discovery.config import project_root
from discovery.shared_library import (
    export_enabled,
    import_all_stephen_packages,
    load_sync_state,
    now_iso,
    save_sync_state,
    sync_visual_packs,
)
from discovery.shared_library_git import git_repo_status, safe_ff_pull


def auto_pull_enabled() -> bool:
    return os.environ.get("BROTHER_AUTO_PULL", "1").strip().lower() not in ("0", "false", "no")


def auto_pull_interval_minutes() -> int:
    try:
        return max(15, int(os.environ.get("BROTHER_AUTO_PULL_MINUTES", "60")))
    except ValueError:
        return 60


def _pull_is_due(state: dict[str, Any], *, interval_minutes: int | None = None) -> bool:
    interval = interval_minutes if interval_minutes is not None else auto_pull_interval_minutes()
    last = state.get("last_code_pull_at")
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


def maybe_auto_brother_code_pull(store, *, force: bool = False) -> dict[str, Any] | None:
    """Fetch + ff-only pull when due. Chris also imports Stephen packages after a pull."""
    if not force and not auto_pull_enabled():
        return None
    state = load_sync_state()
    if not force and not _pull_is_due(state):
        return None

    pull_result = safe_ff_pull()
    import_result = None
    if pull_result.get("pulled") and not export_enabled():
        import_result = import_all_stephen_packages(store)
        if int(import_result.get("imported") or 0) > 0:
            sync_visual_packs(store)

    state = load_sync_state()
    state["last_code_pull_at"] = now_iso()
    if pull_result.get("pulled"):
        state["last_code_pull_at_message"] = pull_result.get("message") or "pulled"
    save_sync_state(state)

    return {
        "auto_code_pull": True,
        "skipped": False,
        "pull": pull_result,
        "import": import_result,
        "git": git_repo_status(fetch=False),
    }


def run_session_start_sync(store) -> dict[str, Any]:
    """Agent/session start: pull code now, import Stephen packages on Chris."""
    return maybe_auto_brother_code_pull(store, force=True) or {
        "auto_code_pull": True,
        "skipped": True,
        "reason": "disabled",
    }
