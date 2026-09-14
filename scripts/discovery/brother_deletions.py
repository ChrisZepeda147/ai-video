"""Cross-brother deletion sync via shared_library/deletions.json in Git."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from discovery.config import project_root, publishing_owner
from discovery.production_library import delete_video, get_video
from discovery.shared_library import (
    find_video_by_manifest_id,
    load_sync_state,
    now_iso,
    save_sync_state,
)
from discovery.shared_library_git import commit_and_push, push_shared_library_deletion

logger = logging.getLogger(__name__)

DELETIONS_VERSION = 1


def deletions_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "shared_library" / "deletions.json"


def load_deletion_log(root: Path | None = None) -> dict[str, Any]:
    path = deletions_path(root)
    if not path.is_file():
        return {"version": DELETIONS_VERSION, "deletions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": DELETIONS_VERSION, "deletions": []}
    data.setdefault("deletions", [])
    return data


def save_deletion_log(data: dict[str, Any], root: Path | None = None) -> None:
    path = deletions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": DELETIONS_VERSION, "deletions": list(data.get("deletions") or [])}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _deletion_key(entry: dict[str, Any]) -> str:
    manifest_id = str(entry.get("manifest_id") or "").strip()
    if manifest_id:
        return f"mid:{manifest_id}"
    owner = str(entry.get("owner") or "").strip().lower()
    slug = str(entry.get("slug") or "").strip()
    return f"slug:{owner}:{slug}"


def append_deletion_record(
    *,
    owner: str,
    slug: str,
    manifest_id: str | None = None,
    deleted_by: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or project_root()
    owner = owner.strip().lower()
    slug = slug.strip()
    if not slug:
        raise ValueError("slug is required for shared deletion")

    entry = {
        "owner": owner,
        "slug": slug,
        "manifest_id": manifest_id or "",
        "deleted_at": now_iso(),
        "deleted_by": (deleted_by or publishing_owner()).strip().lower(),
    }
    data = load_deletion_log(root)
    existing_keys = {_deletion_key(item) for item in data["deletions"]}
    key = _deletion_key(entry)
    if key not in existing_keys:
        data["deletions"].append(entry)
        save_deletion_log(data, root)
    return entry


def _local_videos_for_deletion(store, entry: dict[str, Any]) -> list[int]:
    manifest_id = str(entry.get("manifest_id") or "").strip()
    if manifest_id:
        video = find_video_by_manifest_id(store, manifest_id)
        if video:
            return [int(video["id"])]

    slug = str(entry.get("slug") or "").strip()
    owner = str(entry.get("owner") or "").strip().lower()
    if not slug:
        return []

    rows = store._conn.execute(
        """
        SELECT id, metadata_json FROM production_library_videos
        WHERE slug = ?
        ORDER BY id DESC
        """,
        (slug,),
    ).fetchall()
    ids: list[int] = []
    for row in rows:
        meta: dict[str, Any] = {}
        raw = row["metadata_json"]
        if raw:
            try:
                meta = json.loads(str(raw))
            except json.JSONDecodeError:
                meta = {}
        shared = meta.get("shared_library") or {}
        row_owner = str(shared.get("owner") or meta.get("owner") or "").lower()
        if owner and row_owner and row_owner != owner:
            continue
        ids.append(int(row["id"]))
    return ids


def _remove_local_package(root: Path, owner: str, slug: str) -> bool:
    pkg = root / "shared_library" / owner / slug
    if not pkg.is_dir():
        return False
    shutil.rmtree(pkg)
    return True


def _remove_local_job(root: Path, slug: str) -> bool:
    job = root / "downloads" / "motivational" / slug
    if not job.is_dir():
        return False
    shutil.rmtree(job)
    return True


def apply_shared_deletions(
    store,
    *,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply remote deletion log to local DB, packages, and job dirs."""
    root = root or project_root()
    data = load_deletion_log(root)
    state = load_sync_state(root)
    applied: dict[str, str] = dict(state.get("deletions_applied") or {})

    removed_videos = 0
    removed_packages = 0
    removed_jobs = 0
    items: list[dict[str, Any]] = []

    for entry in data.get("deletions") or []:
        key = _deletion_key(entry)
        deleted_at = str(entry.get("deleted_at") or "")
        if applied.get(key) == deleted_at and not dry_run:
            continue

        slug = str(entry.get("slug") or "")
        owner = str(entry.get("owner") or "").strip().lower()
        video_ids = _local_videos_for_deletion(store, entry)

        item: dict[str, Any] = {
            "key": key,
            "slug": slug,
            "owner": owner,
            "video_ids": video_ids,
            "dry_run": dry_run,
        }
        if dry_run:
            items.append(item)
            continue

        for vid in video_ids:
            delete_video(store, vid)
            removed_videos += 1

        if owner and slug and _remove_local_package(root, owner, slug):
            removed_packages += 1
        if slug and _remove_local_job(root, slug):
            removed_jobs += 1

        imports = state.setdefault("imports", {})
        manifest_id = str(entry.get("manifest_id") or "").strip()
        if manifest_id and manifest_id in imports:
            del imports[manifest_id]

        applied[key] = deleted_at
        items.append(item)

    if not dry_run:
        state["deletions_applied"] = applied
        state["last_deletions_apply_at"] = now_iso()
        save_sync_state(state, root)

    return {
        "entries": len(data.get("deletions") or []),
        "applied": len(items) if not dry_run else 0,
        "removed_videos": removed_videos,
        "removed_packages": removed_packages,
        "removed_jobs": removed_jobs,
        "items": items,
        "dry_run": dry_run,
    }


def reconcile_packages_removed_from_git(
    store,
    *,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Drop imports whose shared package folder disappeared after git pull."""
    root = root or project_root()
    state = load_sync_state(root)
    imports: dict[str, Any] = dict(state.get("imports") or {})
    removed: list[dict[str, Any]] = []

    for manifest_id, record in list(imports.items()):
        slug = str(record.get("slug") or "")
        owner = str(manifest_id).split(":", 1)[0] if ":" in str(manifest_id) else "stephen"
        if not slug:
            continue
        manifest_path = root / "shared_library" / owner / slug / "manifest.json"
        if manifest_path.is_file():
            continue
        removed.append({"manifest_id": manifest_id, "slug": slug, "owner": owner})
        if dry_run:
            continue
        video_id = record.get("video_id")
        if video_id:
            delete_video(store, int(video_id))
        del imports[manifest_id]
        _remove_local_job(root, slug)

    if not dry_run and removed:
        state["imports"] = imports
        save_sync_state(state, root)

    return {"reconciled": len(removed), "items": removed, "dry_run": dry_run}


def propagate_library_video_deletion(
    store,
    video_id: int,
    *,
    root: Path | None = None,
    push_git: bool = True,
    delete_files: bool = True,
) -> dict[str, Any]:
    """Record deletion, remove shared package, optional git push to both remotes."""
    root = root or project_root()
    video = get_video(store, int(video_id))
    if not video:
        raise ValueError(f"Video {video_id} not found")

    meta = video.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    shared = meta.get("shared_library") or {}
    manifest_id = str(shared.get("manifest_id") or "").strip()
    owner = str(shared.get("owner") or meta.get("owner") or publishing_owner()).lower()
    slug = str(video.get("slug") or "").strip()

    entry = append_deletion_record(
        owner=owner,
        slug=slug,
        manifest_id=manifest_id or None,
        root=root,
    )
    pkg_removed = _remove_local_package(root, owner, slug) if owner and slug else False
    job_removed = _remove_local_job(root, slug) if slug else False

    git_result = None
    if push_git and owner and slug:
        git_result = push_shared_library_deletion(
            owner=owner,
            slug=slug,
            message=f"shared library: delete {owner}/{slug}",
        )
        if not git_result.get("ok"):
            logger.warning("Shared deletion git push skipped: %s", git_result.get("message"))

    removed = delete_video(store, int(video_id), delete_files=delete_files, root=root)
    if not removed:
        raise ValueError(f"Video {video_id} not found")

    state = load_sync_state(root)
    if manifest_id and manifest_id in state.get("imports", {}):
        del state["imports"][manifest_id]
        save_sync_state(state, root)

    return {
        "entry": entry,
        "video_id": video_id,
        "package_removed": pkg_removed,
        "job_removed": job_removed,
        "git": git_result,
        "slug": removed.get("slug"),
        "video_key": removed.get("video_key"),
        "removed_paths": removed.get("removed_paths") or [],
    }
