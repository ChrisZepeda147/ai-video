"""Unified video library — site production projects + legacy catalog entries."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field

from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.media_paths import (
    VIDEO_MEDIA_KINDS,
    display_media_path,
    file_exists_rel,
    infer_media_kind,
    is_playable_media,
    is_previewable_output,
)

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
    library_id: int | None = None
    legacy_id: str | None = None
    niche: str | None = None
    duration_sec: float | None = None
    created_at: str | None = None
    rendered_at: str | None = None
    youtube_id: str | None = None
    origin_type: str | None = None
    media_kind: str = "video"
    speaker: str | None = None
    display_path: str | None = None
    editable: bool = True
    monetization_confidence: float | None = None
    rights_confidence: float | None = None
    reuse_confidence: float | None = None
    error_message: str | None = None
    published_to: list[dict[str, Any]] = field(default_factory=list)
    used: bool = False
    finished_bucket: str | None = None
    posting_status: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def production_to_library_item(project, *, root: Path) -> VideoLibraryItem:
    output_path = project.output_path
    output_paths = [output_path] if output_path else []
    preview_available = bool(output_path and is_previewable_output(root, output_path))
    missing_paths = [] if preview_available else ([output_path] if output_path else [])
    return VideoLibraryItem(
        key=f"production:{project.id}",
        source="production",
        project_id=project.id,
        slug=project.slug,
        title=project.title,
        speaker=project.title,
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
        media_kind=infer_media_kind(output_path),
        display_path=display_media_path(output_path),
        monetization_confidence=project.monetization_confidence,
        rights_confidence=project.rights_confidence,
        reuse_confidence=project.reuse_confidence,
        error_message=project.error_message,
    )


def _resolved_media_kind(*, path: str | None, role: str = "", override: str | None = None) -> str:
    if override in VIDEO_MEDIA_KINDS:
        return override
    return infer_media_kind(path, role=role)


def production_library_to_item(video: dict[str, Any], *, root: Path) -> VideoLibraryItem:
    output_path = str(video.get("final_output_path") or "") or None
    output_paths = [output_path] if output_path else []
    preview_available = bool(output_path and is_previewable_output(root, output_path))
    missing_paths = [] if preview_available else ([output_path] if output_path else [])
    slug = str(video.get("slug") or f"video-{video.get('id')}")
    meta = video.get("metadata") if isinstance(video.get("metadata"), dict) else {}
    speaker = str(video.get("speaker") or "").strip() or None
    media_kind = _resolved_media_kind(
        path=output_path,
        override=str(meta.get("media_kind_override") or "") or None,
    )
    used = bool((video.get("posting_status") or {}).get("posted") or video.get("used") or video.get("posted"))
    finished_bucket = str(video.get("finished_bucket") or ("used" if used else "unused"))
    return VideoLibraryItem(
        key=f"library:{video.get('id')}",
        source="library",
        library_id=int(video["id"]),
        slug=slug,
        title=str(video.get("title") or title_from_slug(slug)),
        speaker=speaker,
        format_profile="source_video_visuals",
        origin_type="production_library",
        status=str(video.get("status") or "completed"),
        niche=str(video.get("topic") or "") or None,
        output_path=output_path if preview_available else (output_path if output_path else None),
        output_paths=output_paths,
        preview_available=preview_available,
        missing_paths=missing_paths,
        duration_sec=float(video["duration_sec"]) if video.get("duration_sec") else None,
        created_at=str(video.get("created_at") or "") or None,
        media_kind=media_kind,
        display_path=display_media_path(output_path),
        editable=True,
        used=used,
        finished_bucket=finished_bucket,
        posting_status=video.get("posting_status"),
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
    speaker = str(entry.get("speaker") or "").strip() or None
    title = (
        speaker
        or story_title_for_slug(catalog, slug)
        or str(entry.get("title") or title_from_slug(slug))
    )
    profile = infer_format_profile(primary or slug)
    role = str(entry.get("role") or "")
    kind_override = str(entry.get("media_kind") or "") or None
    base_path = existing[0] if existing else primary
    media_kind = _resolved_media_kind(path=base_path, role=role, override=kind_override)
    if media_kind == "audio":
        preview_path = base_path
        preview_available = bool(
            base_path and is_playable_media(root, base_path, role=role)
        )
    else:
        playable = [
            path
            for path in existing
            if infer_media_kind(path) == "video" and is_previewable_output(root, path, role=role)
        ]
        preview_path = playable[0] if playable else base_path
        preview_available = bool(
            playable
            or (
                preview_path
                and is_previewable_output(root, preview_path, role=role)
            )
        )
    return VideoLibraryItem(
        key=str(entry.get("id") or f"legacy:{slug}"),
        source="legacy",
        legacy_id=str(entry.get("id") or f"video:{slug}"),
        slug=slug,
        title=title,
        speaker=speaker,
        format_profile=profile,
        origin_type="legacy",
        status="approved" if preview_path and file_exists(root, preview_path) else "missing_files",
        niche=infer_niche(primary or slug, slug),
        output_path=preview_path if preview_path and file_exists(root, preview_path) else primary,
        output_paths=output_paths,
        preview_available=preview_available,
        missing_paths=missing,
        youtube_id=entry.get("youtube_id"),
        created_at=catalog.updated_at or None,
        media_kind=media_kind,
        display_path=display_media_path(preview_path or primary),
        editable=True,
    )


def build_video_library(
    store,
    *,
    root: Path | None = None,
    include_missing_legacy: bool = False,
    limit: int = 200,
) -> list[VideoLibraryItem]:
    root = root or project_root()
    catalog = content_reuse.load_persisted(root)
    projects = store.list_production_projects(limit=limit)
    production_slugs = {project.slug for project in projects}

    items: list[VideoLibraryItem] = []
    for project in projects:
        item = production_to_library_item(project, root=root)
        if not include_missing_legacy and not item.preview_available:
            continue
        items.append(item)
    seen_slugs = set(production_slugs)

    from discovery.production_library import list_videos

    for video in list_videos(
        store,
        limit=limit,
        heal=False,
        playable_only=not include_missing_legacy,
    ):
        slug = str(video.get("slug") or "")
        if slug and slug in seen_slugs:
            continue
        lib_item = production_library_to_item(video, root=root)
        if slug:
            seen_slugs.add(slug)
        if not include_missing_legacy and not lib_item.preview_available:
            continue
        items.append(lib_item)

    for entry in catalog.videos:
        slug = str(entry.get("slug") or "")
        if slug and slug in seen_slugs:
            continue
        legacy_item = legacy_to_library_item(entry, root=root, catalog=catalog)
        if slug:
            seen_slugs.add(slug)
        if not include_missing_legacy and not legacy_item.preview_available:
            continue
        items.append(legacy_item)

    from discovery.publishing.links import publishing_links_for_video

    for item in items:
        item.published_to = publishing_links_for_video(
            store,
            project_id=item.project_id,
            slug=item.slug,
        )
        if item.source != "library":
            item.used = bool(item.published_to)
            item.finished_bucket = "used" if item.used else "unused"

    items.sort(
        key=lambda item: (
            0 if item.preview_available else 1,
            item.created_at or "",
            item.title.lower(),
        ),
        reverse=True,
    )
    return items[:limit]


def prune_missing_legacy_catalog(root: Path | None = None) -> dict[str, Any]:
    """Remove legacy used.json rows with missing or invalid (stub/incomplete) media."""
    root = root or project_root()
    catalog = content_reuse.load_persisted(root)
    pruned, removed = content_reuse.prune_unplayable_videos(catalog, root)
    if removed:
        content_reuse.save_catalog(pruned, root)
    return {"removed": removed, "remaining": len(pruned.videos)}


def update_video_library_item(
    store,
    *,
    root: Path | None = None,
    source: str,
    library_id: int | None = None,
    project_id: int | None = None,
    legacy_id: str | None = None,
    speaker: str | None = None,
    media_kind: str | None = None,
    remember_speaker: bool = True,
) -> VideoLibraryItem:
    """Update speaker and/or audio|video category from the Videos dashboard."""
    root = root or project_root()
    speaker = speaker.strip() if speaker else None
    if media_kind is not None:
        kind = media_kind.strip().lower()
        if kind not in {"audio", "video", "video_audio"}:
            raise ValueError("media_kind must be audio, video, or video_audio")
        media_kind = kind

    if source == "library":
        if not library_id:
            raise ValueError("library_id is required for library source")
        from discovery.production_library import get_video, now_iso
        from discovery.speaker_identity import update_video_speaker

        if speaker:
            update_video_speaker(
                store,
                int(library_id),
                speaker,
                remember=remember_speaker,
                corrected_by="videos_tab",
            )
        if media_kind:
            video = get_video(store, int(library_id))
            if not video:
                raise ValueError(f"Video {library_id} not found")
            meta = video.get("metadata") if isinstance(video.get("metadata"), dict) else {}
            meta = dict(meta)
            meta["media_kind_override"] = media_kind
            store._conn.execute(
                """
                UPDATE production_library_videos
                SET metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(meta), now_iso(), int(library_id)),
            )
            store._conn.commit()

    elif source == "legacy":
        if not legacy_id:
            raise ValueError("legacy_id is required for legacy source")
        updated = content_reuse.update_catalog_video_entry(
            legacy_id,
            root=root,
            speaker=speaker,
            media_kind=media_kind,
        )
        if not updated:
            raise ValueError(f"Legacy catalog entry not found: {legacy_id}")

    elif source == "production":
        if not project_id:
            raise ValueError("project_id is required for production source")
        project = store.get_production_project(int(project_id))
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if speaker:
            store._conn.execute(
                "UPDATE production_projects SET title = ? WHERE id = ?",
                (speaker, int(project_id)),
            )
            store._conn.commit()
        if media_kind and project.output_path:
            rel = str(project.output_path)
            catalog = content_reuse.load_persisted(root)
            matched = False
            for row in catalog.videos:
                paths = resolve_output_paths(row)
                if rel in paths or row.get("path") == rel:
                    content_reuse.update_catalog_video_entry(
                        str(row.get("id") or ""),
                        root=root,
                        speaker=speaker,
                        media_kind=media_kind,
                    )
                    matched = True
                    break
            if not matched and legacy_id:
                content_reuse.update_catalog_video_entry(
                    legacy_id,
                    root=root,
                    speaker=speaker,
                    media_kind=media_kind,
                )
        if not speaker and not media_kind:
            raise ValueError("Nothing to update")
    else:
        raise ValueError(f"Unsupported source: {source}")

    if not speaker and not media_kind:
        raise ValueError("Nothing to update")

    items = build_video_library(store, root=root, include_missing_legacy=True, limit=500)
    if source == "library" and library_id:
        for item in items:
            if item.library_id == int(library_id):
                return item
    if source == "production" and project_id:
        for item in items:
            if item.project_id == int(project_id):
                return item
    if source == "legacy" and legacy_id:
        for item in items:
            if item.legacy_id == legacy_id:
                return item
    raise ValueError("Updated item not found in library")


def _delete_listed_local_media(root: Path, rel_paths: list[str], *, slug: str | None = None) -> list[str]:
    from discovery.production_library import JOB_PIPELINES_SAFE_TO_WIPE, job_dir_for_rel, safe_remove_paths

    targets: list[Path] = []
    for rel in rel_paths:
        if not rel:
            continue
        posix = str(rel).replace("\\", "/").lstrip("/")
        path = root / posix
        job = job_dir_for_rel(posix, root)
        targets.append(job if job is not None else path)
    if slug:
        for pipeline in JOB_PIPELINES_SAFE_TO_WIPE:
            candidate = root / "downloads" / pipeline / slug
            if candidate.is_dir():
                targets.append(candidate)
    return safe_remove_paths(root, targets)


def delete_video_library_item(
    store,
    *,
    root: Path | None = None,
    source: str,
    library_id: int | None = None,
    project_id: int | None = None,
    legacy_id: str | None = None,
    slug: str | None = None,
    delete_files: bool = True,
) -> dict[str, Any]:
    """Remove one Videos tab entry and delete its local files."""
    root = root or project_root()
    deleted: dict[str, Any] = {"source": source, "removed_paths": []}

    if source == "legacy":
        if not legacy_id and not slug:
            raise ValueError("legacy_id or slug is required for legacy source")
        removed = content_reuse.delete_catalog_video_entry(
            str(legacy_id or ""),
            root=root,
            slug=slug,
        )
        if not removed:
            raise ValueError("Legacy catalog entry not found")
        deleted["legacy_id"] = removed.get("id") or legacy_id
        deleted["slug"] = removed.get("slug") or slug
        if delete_files:
            paths = resolve_output_paths(removed)
            deleted["removed_paths"] = _delete_listed_local_media(
                root,
                paths,
                slug=str(removed.get("slug") or slug or "") or None,
            )

    elif source == "library":
        if not library_id:
            raise ValueError("library_id is required for library source")
        from discovery.production_library import delete_video

        result = delete_video(store, int(library_id), delete_files=delete_files, root=root)
        if not result:
            raise ValueError(f"Video {library_id} not found")
        deleted["library_id"] = int(library_id)
        deleted["slug"] = result.get("slug")
        deleted["video_key"] = result.get("video_key")
        deleted["removed_paths"] = result.get("removed_paths") or []

    elif source == "production":
        if not project_id:
            raise ValueError("project_id is required for production source")
        project = store.get_production_project(int(project_id))
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if delete_files:
            rels = [str(project.output_path)] if project.output_path else []
            deleted["removed_paths"] = _delete_listed_local_media(root, rels, slug=project.slug)
        if not store.delete_production_project(int(project_id)):
            raise ValueError(f"Project {project_id} not found")
        deleted["project_id"] = int(project_id)
        deleted["slug"] = project.slug
        content_reuse.delete_catalog_video_entry("", root=root, slug=project.slug)
    else:
        raise ValueError(f"Unsupported source: {source}")

    return deleted


def library_summary(items: list[VideoLibraryItem]) -> dict[str, int]:
    return {
        "total": len(items),
        "production": sum(1 for item in items if item.source == "production"),
        "library": sum(1 for item in items if item.source == "library"),
        "legacy": sum(1 for item in items if item.source == "legacy"),
        "audio": sum(1 for item in items if item.media_kind == "audio"),
        "video": sum(1 for item in items if item.media_kind == "video"),
        "video_audio": sum(1 for item in items if item.media_kind == "video_audio"),
        "preview_ready": sum(1 for item in items if item.preview_available),
        "missing_files": sum(1 for item in items if not item.preview_available),
    }
