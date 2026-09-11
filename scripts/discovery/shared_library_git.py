"""Git helpers for shared library sync — safe scoped commits only."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from discovery.config import project_root

ALLOWED_PUSH_PREFIXES = (
    "shared_library/stephen/",
    "shared_library/chris/",
    ".gitattributes",
)
SHARED_LIBRARY_OWNERS = ("stephen", "chris")
PUSH_REMOTES = ("origin", "chris")
SCOPED_PULL_PATHS = (
    "shared_library",
    ".gitattributes",
)


def _run_git(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd or project_root()),
        capture_output=True,
        text=True,
        check=check,
    )


def git_porcelain() -> list[str]:
    result = _run_git(["status", "--porcelain"], check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _path_from_porcelain(line: str) -> str:
    body = line[3:].strip()
    if " -> " in body:
        body = body.split(" -> ", 1)[1]
    return body.replace("\\", "/")


def unrelated_changes(extra_allowed: tuple[str, ...] = ALLOWED_PUSH_PREFIXES) -> list[str]:
    unrelated: list[str] = []
    for line in git_porcelain():
        path = _path_from_porcelain(line)
        if any(path.startswith(prefix) or path == prefix.rstrip("/") for prefix in extra_allowed):
            continue
        unrelated.append(path)
    return unrelated


def _resolve_remote_ref() -> str:
    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
    if upstream.returncode == 0 and upstream.stdout.strip():
        return upstream.stdout.strip()
    for candidate in ("origin/main", "origin/master", "origin/HEAD"):
        probe = _run_git(["rev-parse", "--verify", candidate], check=False)
        if probe.returncode == 0:
            return candidate
    return "origin/HEAD"


def stage_shared_library() -> list[str]:
    root = project_root()
    staged: list[str] = []
    for owner in SHARED_LIBRARY_OWNERS:
        owner_dir = root / "shared_library" / owner
        if owner_dir.is_dir() and any(owner_dir.glob("*/manifest.json")):
            rel = f"shared_library/{owner}"
            _run_git(["add", rel])
            staged.append(rel)
    attrs = root / ".gitattributes"
    if attrs.is_file():
        _run_git(["add", ".gitattributes"])
        staged.append(".gitattributes")
    return staged


def commit_and_push(message: str, *, dry_run: bool = False) -> dict[str, Any]:
    unrelated = unrelated_changes()
    if unrelated:
        return {
            "ok": False,
            "error": "unrelated_changes",
            "unrelated": unrelated,
            "message": "Refusing to commit — unrelated working tree changes detected.",
        }

    staged = stage_shared_library()
    if not staged:
        return {"ok": True, "committed": False, "pushed": False, "message": "Nothing to stage."}

    diff = _run_git(["diff", "--cached", "--name-only"], check=False)
    if not diff.stdout.strip():
        return {"ok": True, "committed": False, "pushed": False, "message": "No staged changes."}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_stage": staged,
            "would_commit_files": diff.stdout.strip().splitlines(),
        }

    commit = _run_git(["commit", "-m", message], check=False)
    if commit.returncode != 0:
        if "nothing to commit" in (commit.stdout + commit.stderr).lower():
            return {"ok": True, "committed": False, "pushed": False, "message": "Nothing to commit."}
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit failed")

    pushed_remotes: list[str] = []
    push_errors: list[str] = []
    for remote in PUSH_REMOTES:
        probe = _run_git(["remote", "get-url", remote], check=False)
        if probe.returncode != 0:
            continue
        push = _run_git(["push", remote], check=False)
        if push.returncode != 0:
            push_errors.append(push.stderr.strip() or push.stdout.strip() or f"git push {remote} failed")
        else:
            pushed_remotes.append(remote)
    if not pushed_remotes:
        raise RuntimeError(push_errors[0] if push_errors else "git push failed")

    return {
        "ok": True,
        "committed": True,
        "pushed": True,
        "pushed_remotes": pushed_remotes,
        "commit_message": message,
        "files": diff.stdout.strip().splitlines(),
    }


def git_repo_status(*, fetch: bool = False) -> dict[str, Any]:
    """Local repo HEAD + how far behind/ahead of upstream (for code/search sync visibility)."""
    if fetch:
        _run_git(["fetch", "origin"], check=False)
        _run_git(["fetch", "chris"], check=False)

    head = _run_git(["rev-parse", "--short", "HEAD"], check=False)
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    ref = _resolve_remote_ref()

    behind = _run_git(["rev-list", "--count", f"HEAD..{ref}"], check=False)
    ahead = _run_git(["rev-list", "--count", f"{ref}..HEAD"], check=False)
    remote_short = _run_git(["rev-parse", "--short", ref], check=False)

    return {
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "commit": head.stdout.strip() if head.returncode == 0 else None,
        "remote_ref": ref,
        "remote_commit": remote_short.stdout.strip() if remote_short.returncode == 0 else None,
        "commits_behind": int(behind.stdout.strip()) if behind.returncode == 0 and behind.stdout.strip().isdigit() else None,
        "commits_ahead": int(ahead.stdout.strip()) if ahead.returncode == 0 and ahead.stdout.strip().isdigit() else None,
        "code_sync_hint": (
            "git pull in repo root for Stephen's latest search/script changes"
            if behind.returncode == 0 and behind.stdout.strip() not in ("", "0")
            else None
        ),
    }


def pull_shared_library(*, dry_run: bool = False) -> dict[str, Any]:
    """Fetch remote and update ONLY shared_library + .gitattributes.

    Does not require a clean working tree — local code changes are left alone.
    """
    if dry_run:
        ref = _resolve_remote_ref()
        return {
            "ok": True,
            "dry_run": True,
            "message": f"Would fetch and checkout {', '.join(SCOPED_PULL_PATHS)} from {ref}",
        }

    fetch = _run_git(["fetch", "origin"], check=False)
    if fetch.returncode != 0:
        fetch = _run_git(["fetch"], check=False)
    if fetch.returncode != 0:
        raise RuntimeError(fetch.stderr.strip() or fetch.stdout.strip() or "git fetch failed")

    ref = _resolve_remote_ref()
    updated: list[str] = []
    warnings: list[str] = []

    for rel_path in SCOPED_PULL_PATHS:
        checkout = _run_git(["checkout", ref, "--", rel_path], check=False)
        if checkout.returncode == 0:
            if checkout.stdout.strip() or checkout.stderr.strip():
                pass
            updated.append(rel_path)
        else:
            err = (checkout.stderr or checkout.stdout or "").strip()
            if "did not match any file" in err.lower() or "pathspec" in err.lower():
                warnings.append(f"{rel_path}: not on remote yet")
            else:
                warnings.append(f"{rel_path}: {err or 'checkout failed'}")

    lfs = _run_git(["lfs", "pull", "--include=shared_library/**"], check=False)
    if lfs.returncode != 0:
        warnings.append("git lfs pull skipped or failed — install Git LFS if media files are missing")

    return {
        "ok": True,
        "pulled": True,
        "method": "scoped_checkout",
        "remote_ref": ref,
        "updated_paths": updated,
        "warnings": warnings,
        "output": (fetch.stdout + fetch.stderr).strip(),
    }
