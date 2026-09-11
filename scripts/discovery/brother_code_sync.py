"""Keep Stephen + Chris source even on both GitHub remotes.

Timer path: auto-commit safe source → stash leftovers → rebase onto
origin/main (then chris/main if needed) → pop stash → push origin + chris.

Never force-push. Never touch secrets, downloads, or local data.
Conflicts abort and report — they do not get smashed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, IO

from discovery.config import project_root
from discovery.shared_library_git import (
    PUSH_REMOTES,
    _path_from_porcelain,
    _run_git,
    git_porcelain,
    git_repo_status,
)

STASH_MESSAGE = "brother-code-sync-auto"
CHECKPOINT_MESSAGE = "brother sync: auto checkpoint"

SOURCE_PREFIXES = (
    "scripts/",
    "web/",
    "api/",
    ".cursor/",
    "discovery/",
)
DENY_PREFIXES = (
    "downloads/",
    "data/",
    "content/used.json",
    "notes/",
)
SECRET_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "credentials.csv",
    }
)


def code_sync_enabled() -> bool:
    return os.environ.get("BROTHER_CODE_SYNC", "1").strip().lower() not in ("0", "false", "no")


def code_auto_commit_enabled() -> bool:
    return os.environ.get("BROTHER_CODE_AUTO_COMMIT", "1").strip().lower() not in ("0", "false", "no")


def brother_sync_interval_minutes() -> int:
    raw = os.environ.get("BROTHER_CODE_SYNC_MINUTES") or os.environ.get("SHARED_LIBRARY_AUTO_SYNC_MINUTES", "5")
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def is_source_path(path: str) -> bool:
    rel = path.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    name = Path(rel).name.lower()
    if name in SECRET_NAMES or (name.startswith(".env.") and name != ".env.example"):
        return False
    if name == ".env":
        return False
    if rel == "scripts/.env":
        return False
    if "/.env." in f"/{rel}" and not rel.endswith(".example"):
        return False
    for denied in DENY_PREFIXES:
        if rel == denied.rstrip("/") or rel.startswith(denied):
            return False
    return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in SOURCE_PREFIXES)


def source_paths_from_porcelain(lines: list[str] | None = None) -> list[str]:
    rows = lines if lines is not None else git_porcelain()
    found: list[str] = []
    for line in rows:
        path = _path_from_porcelain(line)
        if is_source_path(path):
            found.append(path)
    return found


def _count_range(spec: str) -> int | None:
    result = _run_git(["rev-list", "--count", spec], check=False)
    text = result.stdout.strip()
    if result.returncode != 0 or not text.isdigit():
        return None
    return int(text)


def _remote_exists(name: str) -> bool:
    return _run_git(["remote", "get-url", name], check=False).returncode == 0


def _ref_exists(ref: str) -> bool:
    return _run_git(["rev-parse", "--verify", ref], check=False).returncode == 0


def _lock_path() -> Path:
    return project_root() / "data" / "shared_library" / "code_sync.lock"


def _acquire_lock() -> IO[bytes] | None:
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_lock(handle: IO[bytes] | None) -> None:
    if handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()


def fetch_both() -> dict[str, Any]:
    errors: list[str] = []
    fetched: list[str] = []
    for remote in PUSH_REMOTES:
        if not _remote_exists(remote):
            continue
        result = _run_git(["fetch", remote], check=False)
        if result.returncode != 0:
            errors.append(result.stderr.strip() or result.stdout.strip() or f"git fetch {remote} failed")
        else:
            fetched.append(remote)
    return {"ok": not errors, "fetched": fetched, "errors": errors}


def _auto_commit_source() -> dict[str, Any]:
    if not code_auto_commit_enabled():
        return {"ok": True, "committed": False, "skipped": True, "reason": "auto_commit_disabled"}
    paths = source_paths_from_porcelain()
    if not paths:
        return {"ok": True, "committed": False, "files": []}
    for path in paths:
        add = _run_git(["add", "--", path], check=False)
        if add.returncode != 0:
            return {
                "ok": False,
                "committed": False,
                "error": add.stderr.strip() or add.stdout.strip() or f"git add {path} failed",
            }
    cached = _run_git(["diff", "--cached", "--name-only"], check=False)
    files = [line.strip() for line in cached.stdout.splitlines() if line.strip()]
    if not files:
        return {"ok": True, "committed": False, "files": []}
    commit = _run_git(["commit", "-m", CHECKPOINT_MESSAGE], check=False)
    if commit.returncode != 0:
        text = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in text:
            return {"ok": True, "committed": False, "files": []}
        return {
            "ok": False,
            "committed": False,
            "error": commit.stderr.strip() or commit.stdout.strip() or "git commit failed",
        }
    return {"ok": True, "committed": True, "files": files, "message": CHECKPOINT_MESSAGE}


def _stash_if_dirty() -> dict[str, Any]:
    leftover = git_porcelain()
    if not leftover:
        return {"ok": True, "stashed": False}
    stash = _run_git(["stash", "push", "-u", "-m", STASH_MESSAGE], check=False)
    if stash.returncode != 0:
        return {
            "ok": False,
            "stashed": False,
            "error": stash.stderr.strip() or stash.stdout.strip() or "git stash failed",
        }
    return {"ok": True, "stashed": True}


def _stash_pop() -> dict[str, Any]:
    pop = _run_git(["stash", "pop"], check=False)
    if pop.returncode != 0:
        return {
            "ok": False,
            "error": pop.stderr.strip() or pop.stdout.strip() or "git stash pop failed",
            "conflict": "conflict" in (pop.stdout + pop.stderr).lower(),
        }
    return {"ok": True}


def _rebase_onto(ref: str) -> dict[str, Any]:
    behind = _count_range(f"HEAD..{ref}") or 0
    if behind <= 0:
        return {"ok": True, "rebased": False, "ref": ref, "behind": 0}
    rebase = _run_git(["rebase", ref], check=False)
    text = (rebase.stdout + rebase.stderr).lower()
    if rebase.returncode != 0 and "index.lock" in text:
        time.sleep(2)
        rebase = _run_git(["rebase", ref], check=False)
        text = (rebase.stdout + rebase.stderr).lower()
    if rebase.returncode != 0:
        _run_git(["rebase", "--abort"], check=False)
        return {
            "ok": False,
            "rebased": False,
            "ref": ref,
            "conflict": "conflict" in text or "could not apply" in text,
            "error": rebase.stderr.strip() or rebase.stdout.strip() or f"rebase onto {ref} failed",
        }
    return {"ok": True, "rebased": True, "ref": ref, "behind": behind}


def _push_both() -> dict[str, Any]:
    pushed: list[str] = []
    errors: list[str] = []
    for remote in PUSH_REMOTES:
        if not _remote_exists(remote):
            continue
        ahead = _count_range(f"{remote}/main..HEAD")
        if ahead == 0:
            continue
        push = _run_git(["push", remote, "HEAD:main"], check=False)
        if push.returncode != 0:
            errors.append(push.stderr.strip() or push.stdout.strip() or f"git push {remote} failed")
        else:
            pushed.append(remote)
    return {"ok": not errors, "pushed": pushed, "errors": errors}


def sync_source_code(*, dry_run: bool = False) -> dict[str, Any]:
    """Pull + push source on origin and chris. Safe paths only."""
    if not code_sync_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled"}

    lock = _acquire_lock()
    if lock is None:
        return {"ok": False, "step": "lock", "error": "another brother sync is already running"}

    try:
        return _sync_source_code_locked(dry_run=dry_run)
    finally:
        _release_lock(lock)


def _sync_source_code_locked(*, dry_run: bool = False) -> dict[str, Any]:
    fetch = fetch_both()
    if not fetch["ok"]:
        return {"ok": False, "step": "fetch", **fetch}

    if dry_run:
        git = git_repo_status(fetch=False)
        pending = source_paths_from_porcelain()
        return {
            "ok": True,
            "dry_run": True,
            "would_commit": pending,
            "git": git,
            "fetched": fetch["fetched"],
        }

    commit = _auto_commit_source()
    if not commit["ok"]:
        return {"ok": False, "step": "commit", **commit}

    stash = _stash_if_dirty()
    if not stash["ok"]:
        return {"ok": False, "step": "stash", **stash}

    rebases: list[dict[str, Any]] = []
    try:
        if _ref_exists("origin/main"):
            origin_rebase = _rebase_onto("origin/main")
            rebases.append(origin_rebase)
            if not origin_rebase["ok"]:
                return {
                    "ok": False,
                    "step": "rebase",
                    "conflict": True,
                    "commit": commit,
                    "stash": stash,
                    "rebases": rebases,
                    "error": origin_rebase.get("error"),
                }
        if _ref_exists("chris/main"):
            chris_behind = _count_range("HEAD..chris/main") or 0
            if chris_behind > 0:
                chris_rebase = _rebase_onto("chris/main")
                rebases.append(chris_rebase)
                if not chris_rebase["ok"]:
                    return {
                        "ok": False,
                        "step": "rebase",
                        "conflict": True,
                        "commit": commit,
                        "stash": stash,
                        "rebases": rebases,
                        "error": chris_rebase.get("error"),
                    }
    finally:
        pop = _stash_pop() if stash.get("stashed") else {"ok": True, "stashed": False}

    if stash.get("stashed") and not pop.get("ok"):
        return {
            "ok": False,
            "step": "stash_pop",
            "conflict": bool(pop.get("conflict")),
            "commit": commit,
            "stash": stash,
            "rebases": rebases,
            "error": pop.get("error"),
        }

    push = _push_both()
    git = git_repo_status(fetch=False)
    return {
        "ok": bool(push["ok"]),
        "commit": commit,
        "stash": stash,
        "rebases": rebases,
        "push": push,
        "git": git,
        "error": ("; ".join(push["errors"]) if push["errors"] else None),
    }
