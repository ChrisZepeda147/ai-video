"""Register legacy Cursor renders on the site dashboard."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.video_library import (
    infer_format_profile,
    infer_niche,
    resolve_output_paths,
    story_title_for_slug,
    title_from_slug,
)

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import content_reuse  # noqa: E402

logger = logging.getLogger(__name__)


def default_db_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "discovery" / "catalog.sqlite"


def copy_primary_output(
    *,
    root: Path,
    slug: str,
    source_paths: list[str],
    copy_files: bool,
) -> tuple[str | None, list[str]]:
    existing = [path for path in source_paths if (root / path).is_file()]
    if not existing:
        return None, source_paths

    if not copy_files:
        return existing[0], []

    dest_dir = root / "downloads" / "production" / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for index, rel_path in enumerate(existing, start=1):
        src = root / rel_path
        dest_name = "final.mp4" if len(existing) == 1 else f"part{index:02d}.mp4"
        dest = dest_dir / dest_name
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        copied.append(dest.relative_to(root).as_posix())
    return copied[0], []


def import_video_entry(
    store,
    entry: dict[str, Any],
    *,
    root: Path,
    copy_files: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    slug = str(entry.get("slug") or entry.get("id") or "untitled")
    catalog = content_reuse.load_persisted(root)
    title = story_title_for_slug(catalog, slug) or str(entry.get("title") or title_from_slug(slug))
    source_paths = resolve_output_paths(entry)
    primary_path, missing = copy_primary_output(
        root=root,
        slug=slug,
        source_paths=source_paths,
        copy_files=copy_files,
    )
    if not primary_path:
        return {
            "slug": slug,
            "status": "skipped",
            "reason": "missing_files",
            "missing_paths": missing or source_paths,
        }

    from discovery.media_paths import is_previewable_output

    if not is_previewable_output(root, primary_path):
        return {
            "slug": slug,
            "status": "skipped",
            "reason": "unplayable_or_incomplete",
            "missing_paths": missing or source_paths,
        }

    existing = store.get_production_project_by_slug(slug)
    if existing and existing.output_path:
        return {
            "slug": slug,
            "status": "skipped",
            "reason": "already_imported",
            "project_id": existing.id,
            "output_path": existing.output_path,
        }

    format_profile = infer_format_profile(primary_path)
    niche = infer_niche(primary_path, slug)
    if dry_run:
        return {
            "slug": slug,
            "status": "ready",
            "title": title,
            "output_path": primary_path,
            "format_profile": format_profile,
            "niche": niche,
        }

    project_id = existing.id if existing else store.create_production_project(
        slug=slug,
        title=title,
        niche=niche,
        origin_type="legacy",
        format_profile=format_profile,
        hook_text=None,
        caption_preset="viral_bold",
    )
    store.update_production_project_rendered(
        project_id,
        output_path=primary_path,
        duration_sec=0.0,
        monetization_confidence=1.0,
        rights_confidence=1.0,
        reuse_confidence=0.0,
        risk_explanations_json=json.dumps([]),
        status="approved",
    )
    return {
        "slug": slug,
        "status": "imported",
        "project_id": project_id,
        "output_path": primary_path,
        "title": title,
    }


def import_videos_to_site(
    store,
    *,
    root: Path | None = None,
    slugs: list[str] | None = None,
    rebuild_catalog: bool = False,
    copy_files: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = root or project_root()
    if rebuild_catalog:
        content_reuse.rebuild(root)

    catalog = content_reuse.load_persisted(root)
    entries = catalog.videos
    if slugs:
        wanted = set(slugs)
        entries = [entry for entry in entries if str(entry.get("slug")) in wanted]

    results = [
        import_video_entry(
            store,
            entry,
            root=root,
            copy_files=copy_files,
            dry_run=dry_run,
        )
        for entry in entries
    ]
    imported = [item for item in results if item.get("status") == "imported"]
    ready = [item for item in results if item.get("status") == "ready"]
    skipped = [item for item in results if item.get("status") == "skipped"]
    return {
        "results": results,
        "count": len(results),
        "imported_count": len(imported),
        "ready_count": len(ready),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped,
    }


def sync_legacy_renders_to_site(
    *,
    slugs: list[str] | None = None,
    root: Path | None = None,
    db_path: Path | None = None,
    rebuild_catalog: bool = True,
) -> dict[str, Any] | None:
    """Best-effort site registration after a legacy render. Never raises."""
    root = root or project_root()
    db_path = db_path or default_db_path(root)
    if not db_path.is_file():
        logger.info("Site DB missing at %s — skip auto-register", db_path)
        return None
    try:
        from discovery.store import DiscoveryStore

        store = DiscoveryStore(db_path)
        try:
            payload = import_videos_to_site(
                store,
                root=root,
                slugs=slugs,
                rebuild_catalog=rebuild_catalog,
            )
        finally:
            store.close()
        if payload["imported_count"]:
            titles = ", ".join(item.get("title") or item.get("slug", "") for item in payload["imported"])
            print(f"Added to site: {titles}")
        return payload
    except Exception as exc:
        logger.warning("Site auto-register failed: %s", exc)
        return {"status": "failed", "reason": str(exc)}
