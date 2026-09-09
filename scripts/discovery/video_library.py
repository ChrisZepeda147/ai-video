"""Unified video library — site production projects + legacy catalog entries."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from discovery.config import project_root

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import content_reuse  # noqa: E402


def title_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


def infer_format_profile(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    if "/imessage/" in normalized or "/story/" in normalized:
        return "original_story"
    if "/youtube/" in normalized or "/motivational/" in normalized:
        return "source_video_visuals"
    if "/stills/" in normalized:
        return "audio_visuals"
    if "/production/" in normalized:
        return "audio_visuals"
    return "audio_visuals"


def infer_niche(path: str, slug: str) -> str | None:
    normalized = path.replace("\\", "/").lower()
    if "/imessage/" in normalized:
        return "horror"
    if "/motivational/" in normalized:
        return "motivation"
    if "/stills/" in normalized:
        return "luxury"
    if "/youtube/" in normalized:
        return "gaming"
    return None


def resolve_output_paths(entry: dict[str, Any]) -> list[str]:
    paths = list(entry.get("paths") or [])
    primary = entry.get("path")
    if primary and primary not in paths:
        paths.insert(0, primary)
    deduped: list[str] = []
    for path in paths:
        if path and path not in deduped:
            deduped.append(path)
    return deduped


def story_title_for_slug(catalog: content_reuse.Catalog, slug: str) -> str | None:
    for story in catalog.stories:
        if story.get("slug") == slug and story.get("title"):
            return str(story["title"])
    return None


def file_exists(root: Path, rel_path: str) -> bool:
    return (root / rel_path).is_file()


@dataclass
class VideoLibraryItem:
    key: str
    source: str
    slug: str
    title: str
    format_profile: str
    status: str
    output_path: str | None
    output_paths: list[str]
    preview_available: bool
    missing_paths: list[str]
    project_id: int | None = None
    legacy_id: str | None = None
    niche: str | None = None
    duration_sec: float | None = None
    created_at: str | None = None
    rendered_at: str | None = None
    youtube_id: str | None = None
    origin_type: str | None = None
    monetization_confidence: float | None = None
    rights_confidence: float | None = None
    reuse_confidence: float | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def production_to_library_item(project, *, root: Path) -> VideoLibraryItem:
    output_path = project.output_path
    output_paths = [output_path] if output_path else []
    preview_available = bool(output_path and file_exists(root, output_path))
    missing_paths = [] if preview_available else ([output_path] if output_path else [])
    return VideoLibraryItem(
        key=f"production:{project.id}",
        source="production",
        project_id=project.id,
        slug=project.slug,
        title=project.title,
        format_profile=project.format_profile,
        origin_type=project.origin_type,
        status=project.status,
        niche=project.niche,
        output_path=output_path,
        output_paths=output_paths,
        preview_available=preview_available,
        missing_paths=missing_paths,
        duration_sec=project.duration_sec,
        created_at=project.created_at,
        rendered_at=project.rendered_at,
        monetization_confidence=project.monetization_confidence,
        rights_confidence=project.rights_confidence,
        reuse_confidence=project.reuse_confidence,
        error_message=project.error_message,
    )


def legacy_to_library_item(
    entry: dict[str, Any],
    *,
    root: Path,
    catalog: content_reuse.Catalog,
) -> VideoLibraryItem:
    slug = str(entry.get("slug") or entry.get("id") or "untitled")
    output_paths = resolve_output_paths(entry)
    primary = output_paths[0] if output_paths else None
    existing = [path for path in output_paths if file_exists(root, path)]
    missing = [path for path in output_paths if not file_exists(root, path)]
    title = story_title_for_slug(catalog, slug) or str(entry.get("title") or title_from_slug(slug))
    profile = infer_format_profile(primary or slug)
    return VideoLibraryItem(
        key=str(entry.get("id") or f"legacy:{slug}"),
        source="legacy",
        legacy_id=str(entry.get("id") or f"video:{slug}"),
        slug=slug,
        title=title,
        format_profile=profile,
        origin_type="legacy",
        status="approved" if existing else "missing_files",
        niche=infer_niche(primary or slug, slug),
        output_path=existing[0] if existing else primary,
        output_paths=output_paths,
        preview_available=bool(existing),
        missing_paths=missing,
        youtube_id=entry.get("youtube_id"),
        created_at=catalog.updated_at or None,
    )


def build_video_library(
    store,
    *,
    root: Path | None = None,
    include_missing_legacy: bool = True,
    limit: int = 200,
) -> list[VideoLibraryItem]:
    root = root or project_root()
    catalog = content_reuse.load_persisted(root)
    projects = store.list_production_projects(limit=limit)
    production_slugs = {project.slug for project in projects}

    items = [production_to_library_item(project, root=root) for project in projects]

    for entry in catalog.videos:
        slug = str(entry.get("slug") or "")
        if slug and slug in production_slugs:
            continue
        legacy_item = legacy_to_library_item(entry, root=root, catalog=catalog)
        if not include_missing_legacy and not legacy_item.preview_available:
            continue
        items.append(legacy_item)

    items.sort(
        key=lambda item: (
            0 if item.preview_available else 1,
            item.created_at or "",
            item.title.lower(),
        ),
        reverse=True,
    )
    return items[:limit]


def library_summary(items: list[VideoLibraryItem]) -> dict[str, int]:
    return {
        "total": len(items),
        "production": sum(1 for item in items if item.source == "production"),
        "legacy": sum(1 for item in items if item.source == "legacy"),
        "preview_ready": sum(1 for item in items if item.preview_available),
        "missing_files": sum(1 for item in items if not item.preview_available),
    }
