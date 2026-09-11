"""Shared library packages — Stephen + Chris export via GitHub, both sides import."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.auto_register import (
    _components_from_job_dir,
    _motivation_payload_fallback,
    _probe_duration_sec,
    _read_json3_transcript,
    _read_url_txt,
    _rel,
)
from discovery.combinations import import_usage_from_videos, sync_visual_packs
from discovery.config import project_root
from discovery.production_library import get_video, register_video
from discovery.reuse_detection import transcript_hash

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
SHARED_OWNER = "stephen"
SHARED_LIBRARY_OWNERS = ("stephen", "chris")
SKIP_JOB_NAMES = frozenset({"config.json"})


def export_owner() -> str | None:
    raw = os.environ.get("SHARED_LIBRARY_EXPORT_OWNER", "").strip().lower()
    if raw in SHARED_LIBRARY_OWNERS:
        return raw
    return None


def auto_push_enabled() -> bool:
    return os.environ.get("SHARED_LIBRARY_AUTO_PUSH", "1").strip().lower() not in ("0", "false", "no")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def shared_library_root(owner: str | None = None, root: Path | None = None) -> Path:
    resolved = owner or export_owner() or SHARED_OWNER
    return (root or project_root()) / "shared_library" / resolved


def shared_library_owners_on_disk(root: Path | None = None) -> list[str]:
    base = (root or project_root()) / "shared_library"
    if not base.is_dir():
        return []
    owners: list[str] = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name in SHARED_LIBRARY_OWNERS:
            owners.append(child.name)
    return owners


def sync_state_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "shared_library" / "sync_state.json"


def export_enabled() -> bool:
    return export_owner() is not None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_sync_state(root: Path | None = None) -> dict[str, Any]:
    path = sync_state_path(root)
    data = _load_json(path)
    data.setdefault("imports", {})
    data.setdefault("exports", {})
    return data


def save_sync_state(state: dict[str, Any], root: Path | None = None) -> None:
    _save_json(sync_state_path(root), state)


def manifest_id_for(*, owner: str, slug: str, final_hash: str) -> str:
    short = final_hash[:16] if final_hash else slug
    safe_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-") or "video"
    return f"{owner}:{safe_slug}:{short}"


def _find_job_output(job_dir: Path) -> Path | None:
    output_dir = job_dir / "output"
    preferred = output_dir / f"{job_dir.name}-motivation.mp4"
    if preferred.is_file():
        return preferred
    if output_dir.is_dir():
        candidates = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return None


def _infer_category(visual_style: str, title: str) -> str:
    from discovery.combinations import _infer_category as combo_infer

    return combo_infer(visual_style, title)


def build_manifest_from_job(
    slug: str,
    *,
    root: Path | None = None,
    owner: str = SHARED_OWNER,
    parent_manifest_id: str | None = None,
    version: int = 1,
    version_label: str | None = None,
    change_summary: str | None = None,
) -> dict[str, Any] | None:
    root = root or project_root()
    job_dir = root / "downloads" / "motivational" / slug
    if not job_dir.is_dir():
        return None

    final_src = _find_job_output(job_dir)
    if not final_src or not final_src.is_file():
        return None

    payload = _load_json(job_dir / "job.json")
    fallback = _motivation_payload_fallback(job_dir)
    if fallback:
        payload = {**fallback, **payload}

    caps = job_dir / "audio" / "subs.en.json3"
    transcript = _read_json3_transcript(caps)
    speech_url = payload.get("speech_url") or _read_url_txt(job_dir)
    speech_id = payload.get("speech_id") or ""
    speaker = str(payload.get("speaker") or "").strip()
    broll_ids = [str(x) for x in (payload.get("broll_ids") or []) if x]
    visual_style = str(payload.get("visual_style") or payload.get("broll_query") or "")
    duration = payload.get("audio_duration") or _probe_duration_sec(final_src)
    title = str(payload.get("speech_title") or slug.replace("-", " ").title())
    final_hash = _sha256_file(final_src)

    paths: dict[str, Any] = {"final": "final.mp4"}
    hashes: dict[str, str] = {"final": final_hash}

    audio = job_dir / "audio" / "speech.mp3"
    if audio.is_file():
        paths["audio"] = "audio/speech.mp3"
        hashes["audio"] = _sha256_file(audio)
    if caps.is_file():
        paths["caption"] = "captions/subs.en.json3"
        hashes["caption"] = _sha256_file(caps)

    visuals: list[str] = []
    clips_dir = job_dir / "clips"
    if clips_dir.is_dir():
        for clip in sorted(clips_dir.glob("*_part*.mp4")):
            rel = f"visuals/{clip.name}"
            visuals.append(rel)
            hashes[rel] = _sha256_file(clip)
    if visuals:
        paths["visuals"] = visuals

    if transcript:
        paths["transcript"] = "transcript.txt"

    ts = now_iso()
    return {
        "manifest_version": MANIFEST_VERSION,
        "manifest_id": manifest_id_for(owner=owner, slug=slug, final_hash=final_hash),
        "owner": owner,
        "slug": slug,
        "title": title,
        "speaker": speaker or None,
        "source_url": speech_url or None,
        "source_external_id": speech_id or None,
        "source_start_sec": payload.get("speech_start"),
        "source_end_sec": None,
        "transcript": transcript or None,
        "transcript_hash": transcript_hash(transcript or ""),
        "duration_sec": float(duration) if duration else None,
        "topic": payload.get("topic"),
        "visual_style": visual_style or None,
        "visual_category": _infer_category(visual_style, title),
        "broll_ids": broll_ids,
        "parent_manifest_id": parent_manifest_id,
        "version": version,
        "version_label": version_label,
        "change_summary": change_summary,
        "paths": paths,
        "hashes": hashes,
        "pipeline": payload.get("pipeline") or "build_motivation_job",
        "created_at": ts,
        "updated_at": ts,
    }


def build_manifest_from_video(
    store,
    video_id: int,
    *,
    root: Path | None = None,
    owner: str = SHARED_OWNER,
) -> dict[str, Any] | None:
    video = get_video(store, video_id)
    if not video:
        return None
    slug = str(video.get("slug") or f"video-{video_id}")
    manifest = build_manifest_from_job(slug, root=root, owner=owner)
    if manifest:
        meta = video.get("metadata") or {}
        if video.get("parent_video_id"):
            parent = get_video(store, int(video["parent_video_id"]))
            if parent:
                parent_meta = parent.get("metadata") or {}
                parent_mid = (parent_meta.get("shared_library") or {}).get("manifest_id")
                if parent_mid:
                    manifest["parent_manifest_id"] = parent_mid
        manifest["title"] = video.get("title") or manifest["title"]
        manifest["version"] = int(video.get("version") or 1)
        manifest["version_label"] = video.get("version_label")
        manifest["change_summary"] = video.get("change_summary")
        manifest["speaker"] = video.get("speaker") or manifest.get("speaker")
        manifest["source_url"] = video.get("source_url") or manifest.get("source_url")
        manifest["source_external_id"] = video.get("source_external_id") or manifest.get("source_external_id")
        manifest["source_start_sec"] = video.get("source_start_sec")
        manifest["source_end_sec"] = video.get("source_end_sec")
        manifest["transcript"] = video.get("transcript_segment") or manifest.get("transcript")
        manifest["duration_sec"] = video.get("duration_sec") or manifest.get("duration_sec")
        if meta.get("broll_ids"):
            manifest["broll_ids"] = meta.get("broll_ids")
        if meta.get("visual_style"):
            manifest["visual_style"] = meta.get("visual_style")
        if meta.get("owner"):
            manifest["owner"] = meta.get("owner")
        return manifest

    root = root or project_root()
    rel_final = video.get("final_output_path")
    if not rel_final:
        return None
    final_src = root / rel_final
    if not final_src.is_file():
        return None
    final_hash = _sha256_file(final_src)
    meta = video.get("metadata") or {}
    transcript = video.get("transcript_segment") or ""
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "manifest_id": manifest_id_for(owner=owner, slug=slug, final_hash=final_hash),
        "owner": owner,
        "slug": slug,
        "title": video.get("title"),
        "speaker": video.get("speaker"),
        "source_url": video.get("source_url"),
        "source_external_id": video.get("source_external_id"),
        "source_start_sec": video.get("source_start_sec"),
        "source_end_sec": video.get("source_end_sec"),
        "transcript": transcript or None,
        "transcript_hash": video.get("transcript_hash") or transcript_hash(transcript),
        "duration_sec": video.get("duration_sec"),
        "topic": video.get("topic"),
        "visual_style": meta.get("visual_style"),
        "visual_category": _infer_category(str(meta.get("visual_style") or ""), str(video.get("title") or "")),
        "broll_ids": meta.get("broll_ids") or [],
        "parent_manifest_id": None,
        "version": int(video.get("version") or 1),
        "version_label": video.get("version_label"),
        "change_summary": video.get("change_summary"),
        "paths": {"final": "final.mp4"},
        "hashes": {"final": final_hash},
        "pipeline": meta.get("pipeline") or "production_library",
        "created_at": video.get("created_at") or now_iso(),
        "updated_at": now_iso(),
    }
    return manifest


def _copy_if_changed(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and _sha256_file(src) == _sha256_file(dest):
        return False
    shutil.copy2(src, dest)
    return True


def export_manifest_package(
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
    job_dir: Path | None = None,
) -> dict[str, Any]:
    """Copy media into shared_library/stephen/<slug>/ and write manifest.json."""
    root = root or project_root()
    slug = str(manifest["slug"])
    owner = str(manifest.get("owner") or SHARED_OWNER)
    package_dir = root / "shared_library" / owner / slug
    package_dir.mkdir(parents=True, exist_ok=True)

    if job_dir is None:
        job_dir = root / "downloads" / "motivational" / slug

    copied: list[str] = []
    paths = manifest.get("paths") or {}

    final_src = _find_job_output(job_dir) if job_dir.is_dir() else None
    if not final_src and manifest.get("final_output_path"):
        final_src = root / str(manifest["final_output_path"])
    if final_src and final_src.is_file():
        if _copy_if_changed(final_src, package_dir / "final.mp4"):
            copied.append("final.mp4")

    audio_src = job_dir / "audio" / "speech.mp3"
    if audio_src.is_file() and paths.get("audio"):
        if _copy_if_changed(audio_src, package_dir / paths["audio"]):
            copied.append(paths["audio"])

    cap_src = job_dir / "audio" / "subs.en.json3"
    if cap_src.is_file() and paths.get("caption"):
        if _copy_if_changed(cap_src, package_dir / paths["caption"]):
            copied.append(paths["caption"])

    clips_dir = job_dir / "clips"
    visuals = paths.get("visuals") or []
    if clips_dir.is_dir() and visuals:
        for rel in visuals:
            name = Path(rel).name
            src = clips_dir / name
            if src.is_file() and _copy_if_changed(src, package_dir / rel):
                copied.append(rel)

    transcript = manifest.get("transcript")
    if transcript and paths.get("transcript"):
        dest = package_dir / paths["transcript"]
        text = str(transcript)
        if not dest.is_file() or dest.read_text(encoding="utf-8") != text:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            copied.append(paths["transcript"])

    manifest["updated_at"] = now_iso()
    manifest["exported_at"] = manifest["updated_at"]
    _save_json(package_dir / "manifest.json", manifest)

    state = load_sync_state(root)
    state.setdefault("exports", {})[manifest["manifest_id"]] = {
        "slug": slug,
        "exported_at": manifest["exported_at"],
        "package_dir": _rel(package_dir, root),
    }
    save_sync_state(state, root)

    return {
        "manifest_id": manifest["manifest_id"],
        "slug": slug,
        "package_dir": _rel(package_dir, root),
        "copied": copied,
        "skipped_duplicate_files": not copied,
    }


def find_stephen_job_slugs(root: Path | None = None) -> list[str]:
    root = root or project_root()
    jobs_root = root / "downloads" / "motivational"
    if not jobs_root.is_dir():
        return []
    slugs: list[str] = []
    for job_dir in sorted(jobs_root.iterdir()):
        if not job_dir.is_dir() or job_dir.name in SKIP_JOB_NAMES:
            continue
        if job_dir.name.startswith("combo-"):
            continue
        if _find_job_output(job_dir):
            slugs.append(job_dir.name)
    return slugs


def export_owner_existing(
    store=None,
    *,
    owner: str | None = None,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = root or project_root()
    owner = owner or export_owner() or SHARED_OWNER
    slugs = find_stephen_job_slugs(root)
    exported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    state = load_sync_state(root)
    known_ids = set(state.get("exports", {}).keys())
    owner_root = shared_library_root(owner, root)

    for slug in slugs:
        try:
            manifest = build_manifest_from_job(slug, root=root, owner=owner)
            if not manifest:
                errors.append({"slug": slug, "error": "no_manifest"})
                continue
            mid = manifest["manifest_id"]
            existing_manifest = owner_root / slug / "manifest.json"
            if mid in known_ids and existing_manifest.is_file():
                on_disk = _load_json(existing_manifest)
                if on_disk.get("hashes", {}).get("final") == manifest["hashes"].get("final"):
                    skipped.append({"slug": slug, "manifest_id": mid, "reason": "already_exported"})
                    continue
            if dry_run:
                exported.append({"slug": slug, "manifest_id": mid, "dry_run": True})
                continue
            result = export_manifest_package(manifest, root=root)
            exported.append(result)
        except Exception as exc:  # noqa: BLE001
            errors.append({"slug": slug, "error": str(exc)})

    if store is not None:
        rows = store._conn.execute(
            """
            SELECT id, slug, final_output_path, metadata_json
            FROM production_library_videos
            WHERE final_output_path IS NOT NULL AND final_output_path != ''
            ORDER BY id ASC
            """
        ).fetchall()
        for row in rows:
            try:
                meta = _parse_json(row["metadata_json"])
                shared = meta.get("shared_library") or {}
                if shared.get("manifest_id"):
                    continue
                manifest = build_manifest_from_video(store, int(row["id"]), root=root, owner=owner)
                if not manifest:
                    continue
                mid = manifest["manifest_id"]
                slug = str(row["slug"] or manifest["slug"])
                existing_manifest = owner_root / slug / "manifest.json"
                if mid in known_ids and existing_manifest.is_file():
                    on_disk = _load_json(existing_manifest)
                    if on_disk.get("hashes", {}).get("final") == manifest["hashes"].get("final"):
                        skipped.append({"slug": slug, "manifest_id": mid, "reason": "already_exported"})
                        continue
                if dry_run:
                    exported.append({"slug": slug, "manifest_id": mid, "dry_run": True, "source": "production_library"})
                    continue
                result = export_manifest_package(manifest, root=root)
                exported.append({**result, "source": "production_library"})
            except Exception as exc:  # noqa: BLE001
                errors.append({"slug": row["slug"], "error": str(exc), "source": "production_library"})

    return {
        "owner": owner,
        "scanned": len(slugs),
        "exported": len(exported),
        "skipped": len(skipped),
        "errors": errors,
        "exported_items": exported,
        "skipped_items": skipped,
        "dry_run": dry_run,
    }


def export_stephen_existing(store=None, *, root: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    return export_owner_existing(store, owner=SHARED_OWNER, root=root, dry_run=dry_run)


def maybe_push_shared_library(*, owner: str | None = None, root: Path | None = None) -> dict[str, Any] | None:
    """Best-effort git commit+push for shared_library only — never raises."""
    if not export_enabled() or not auto_push_enabled():
        return None
    owner = owner or export_owner()
    if not owner:
        return None
    try:
        from discovery.shared_library_git import commit_and_push

        message = f"shared library: {owner} auto sync"
        result = commit_and_push(message, dry_run=False)
        if result.get("ok") and result.get("committed"):
            state = load_sync_state(root)
            state["last_push_at"] = now_iso()
            save_sync_state(state, root)
        return result
    except Exception as exc:
        logger.warning("Shared library auto-push skipped: %s", exc)
        return None


def export_after_register(
    *,
    slug: str | None = None,
    video: dict[str, Any] | None = None,
    store=None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Best-effort export hook — never raises."""
    owner = export_owner()
    if not owner:
        return None
    try:
        root = root or project_root()
        slug = slug or (video or {}).get("slug")
        if not slug:
            return None
        manifest = build_manifest_from_job(str(slug), root=root, owner=owner)
        if not manifest and store and video and video.get("id"):
            manifest = build_manifest_from_video(store, int(video["id"]), root=root, owner=owner)
        if not manifest:
            return None
        result = export_manifest_package(manifest, root=root)
        maybe_push_shared_library(owner=owner, root=root)
        return result
    except Exception as exc:
        logger.warning("Shared library export skipped: %s", exc)
        return None


def export_stephen_after_register(
    *,
    slug: str | None = None,
    video: dict[str, Any] | None = None,
    store=None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    return export_after_register(slug=slug, video=video, store=store, root=root)


def validate_manifest(manifest: dict[str, Any], package_dir: Path) -> list[str]:
    issues: list[str] = []
    for field in ("manifest_id", "owner", "slug", "paths"):
        if not manifest.get(field):
            issues.append(f"missing {field}")
    paths = manifest.get("paths") or {}
    final_rel = paths.get("final")
    if final_rel and not (package_dir / final_rel).is_file():
        issues.append(f"missing final file: {final_rel}")
    hashes = manifest.get("hashes") or {}
    if final_rel and (package_dir / final_rel).is_file():
        actual = _sha256_file(package_dir / final_rel)
        expected = hashes.get("final") or hashes.get(final_rel)
        if expected and actual != expected:
            issues.append("final hash mismatch")
    return issues


def find_video_by_manifest_id(store, manifest_id: str) -> dict[str, Any] | None:
    rows = store._conn.execute(
        """
        SELECT id FROM production_library_videos
        WHERE metadata_json LIKE ?
        ORDER BY id DESC LIMIT 1
        """,
        (f'%"manifest_id": "{manifest_id}"%',),
    ).fetchall()
    for row in rows:
        video = get_video(store, int(row["id"]))
        if video:
            meta = video.get("metadata") or {}
            shared = meta.get("shared_library") or {}
            if shared.get("manifest_id") == manifest_id:
                return video
    state = load_sync_state()
    imp = state.get("imports", {}).get(manifest_id)
    if imp and imp.get("video_id"):
        return get_video(store, int(imp["video_id"]))
    return None


def _materialize_job_from_package(manifest: dict[str, Any], package_dir: Path, root: Path) -> Path:
    slug = str(manifest["slug"])
    job_dir = root / "downloads" / "motivational" / slug
    paths = manifest.get("paths") or {}

    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_dest = output_dir / f"{slug}-motivation.mp4"
    final_src = package_dir / str(paths.get("final") or "final.mp4")
    if final_src.is_file():
        shutil.copy2(final_src, final_dest)

    if paths.get("audio"):
        src = package_dir / paths["audio"]
        dest = job_dir / "audio" / "speech.mp3"
        if src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    if paths.get("caption"):
        src = package_dir / paths["caption"]
        dest = job_dir / "audio" / "subs.en.json3"
        if src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    clips_dir = job_dir / "clips"
    for rel in paths.get("visuals") or []:
        src = package_dir / rel
        if src.is_file():
            clips_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, clips_dir / src.name)

    job_json = {
        "slug": slug,
        "speaker": manifest.get("speaker"),
        "speech_url": manifest.get("source_url"),
        "speech_id": manifest.get("source_external_id"),
        "speech_title": manifest.get("title"),
        "audio_duration": manifest.get("duration_sec"),
        "speech_start": manifest.get("source_start_sec"),
        "broll_ids": manifest.get("broll_ids") or [],
        "visual_style": manifest.get("visual_style"),
        "broll_query": manifest.get("visual_style"),
        "pipeline": manifest.get("pipeline") or "shared_library_import",
        "shared_library_manifest_id": manifest.get("manifest_id"),
    }
    (job_dir / "job.json").write_text(json.dumps(job_json, indent=2), encoding="utf-8")
    if manifest.get("source_url"):
        (job_dir / "url.txt").write_text(f"{manifest['source_url']}\n", encoding="utf-8")
    return job_dir


def import_manifest(
    store,
    manifest: dict[str, Any],
    *,
    package_dir: Path,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = root or project_root()
    manifest_id = str(manifest["manifest_id"])
    slug = str(manifest["slug"])

    existing = find_video_by_manifest_id(store, manifest_id)
    if existing:
        return {
            "manifest_id": manifest_id,
            "slug": slug,
            "status": "already_imported",
            "video_id": existing["id"],
        }

    issues = validate_manifest(manifest, package_dir)
    if issues:
        return {"manifest_id": manifest_id, "slug": slug, "status": "invalid", "issues": issues}

    if dry_run:
        return {"manifest_id": manifest_id, "slug": slug, "status": "would_import", "dry_run": True}

    slug_row = store._conn.execute(
        "SELECT id, metadata_json FROM production_library_videos WHERE slug = ? ORDER BY id DESC LIMIT 1",
        (slug,),
    ).fetchone()
    if slug_row:
        existing_meta = _parse_json(slug_row["metadata_json"])
        existing_mid = (existing_meta.get("shared_library") or {}).get("manifest_id")
        if existing_mid != manifest_id:
            owner_suffix = str(manifest.get("owner") or SHARED_OWNER)
            slug = f"{slug}-{owner_suffix}"

    job_dir = _materialize_job_from_package(manifest, package_dir, root)
    rel_output = _rel(job_dir / "output" / f"{slug}-motivation.mp4", root)

    parent_video_id = None
    parent_mid = manifest.get("parent_manifest_id")
    if parent_mid:
        parent = find_video_by_manifest_id(store, str(parent_mid))
        if parent:
            parent_video_id = int(parent["id"])

    components = _components_from_job_dir(job_dir, root)
    if manifest.get("source_url"):
        components.insert(
            0,
            {
                "component_type": "source",
                "url": manifest["source_url"],
                "label": f"YouTube {manifest.get('source_external_id') or ''}".strip(),
            },
        )

    metadata = {
        "owner": manifest.get("owner") or SHARED_OWNER,
        "pipeline": manifest.get("pipeline") or "shared_library_import",
        "broll_ids": manifest.get("broll_ids") or [],
        "visual_style": manifest.get("visual_style"),
        "shared_library": {
            "manifest_id": manifest_id,
            "imported_at": now_iso(),
            "package_dir": _rel(package_dir, root),
            "owner": manifest.get("owner") or SHARED_OWNER,
        },
    }

    video = register_video(
        store,
        title=str(manifest.get("title") or slug),
        slug=slug,
        speaker=manifest.get("speaker"),
        podcast_source=manifest.get("speaker"),
        source_url=manifest.get("source_url"),
        source_platform="youtube" if manifest.get("source_external_id") else None,
        source_external_id=manifest.get("source_external_id"),
        source_start_sec=manifest.get("source_start_sec"),
        source_end_sec=manifest.get("source_end_sec"),
        transcript_segment=manifest.get("transcript"),
        topic=manifest.get("topic") or "motivation",
        parent_video_id=parent_video_id,
        version_label=manifest.get("version_label"),
        change_summary=manifest.get("change_summary") or f"Imported from shared library ({manifest_id})",
        final_output_path=rel_output,
        duration_sec=float(manifest["duration_sec"]) if manifest.get("duration_sec") else None,
        components=components,
        metadata=metadata,
        copy_final_to_library=True,
    )

    state = load_sync_state(root)
    state.setdefault("imports", {})[manifest_id] = {
        "video_id": int(video["id"]),
        "slug": slug,
        "imported_at": now_iso(),
    }
    state["last_import_at"] = now_iso()
    save_sync_state(state, root)

    return {
        "manifest_id": manifest_id,
        "slug": slug,
        "status": "imported",
        "video_id": int(video["id"]),
    }


def import_all_shared_packages(
    store,
    *,
    root: Path | None = None,
    dry_run: bool = False,
    owners: list[str] | None = None,
) -> dict[str, Any]:
    root = root or project_root()
    owners = owners or shared_library_owners_on_disk(root) or list(SHARED_LIBRARY_OWNERS)

    imported = skipped = errors = 0
    items: list[dict[str, Any]] = []
    manifest_paths: list[Path] = []
    for owner in owners:
        base = root / "shared_library" / owner
        if not base.is_dir():
            continue
        manifest_paths.extend(sorted(base.glob("*/manifest.json")))

    if not manifest_paths:
        return {"found": 0, "imported": 0, "skipped": 0, "errors": [], "items": [], "owners": owners}

    for manifest_path in manifest_paths:
        manifest = _load_json(manifest_path)
        if not manifest:
            errors += 1
            items.append({"path": str(manifest_path), "status": "invalid_json"})
            continue
        try:
            result = import_manifest(
                store,
                manifest,
                package_dir=manifest_path.parent,
                root=root,
                dry_run=dry_run,
            )
            items.append(result)
            if result.get("status") == "imported":
                imported += 1
            elif result.get("status") == "already_imported":
                skipped += 1
            elif result.get("status") in {"invalid", "error"}:
                errors += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            items.append({"slug": manifest.get("slug"), "status": "error", "error": str(exc)})

    if not dry_run and imported:
        sync_visual_packs(store)
        new_ids = [item["video_id"] for item in items if item.get("status") == "imported" and item.get("video_id")]
        imported_owners = {
            str((item.get("manifest_id") or "").split(":", 1)[0])
            for item in items
            if item.get("status") == "imported" and item.get("manifest_id")
        }
        usage = {"imported": 0, "skipped": 0}
        for pack_owner in imported_owners:
            owner_ids = [
                item["video_id"]
                for item in items
                if item.get("status") == "imported"
                and item.get("video_id")
                and str(item.get("manifest_id", "")).startswith(f"{pack_owner}:")
            ]
            if owner_ids:
                part = import_usage_from_videos(store, owner=pack_owner, video_ids=owner_ids)
                usage["imported"] += int(part.get("imported", 0) or 0)
                usage["skipped"] += int(part.get("skipped", 0) or 0)
        new_slugs = [str(item["slug"]) for item in items if item.get("status") == "imported" and item.get("slug")]
        if new_slugs:
            try:
                from discovery.site_videos import sync_legacy_renders_to_site

                sync_legacy_renders_to_site(slugs=new_slugs, root=root, rebuild_catalog=False)
            except Exception as exc:  # noqa: BLE001 — site dashboard is best-effort
                logger.warning("Site sync after shared import failed: %s", exc)
    else:
        usage = {"imported": 0, "skipped": 0}

    state = load_sync_state(root)
    state["last_import_at"] = now_iso()
    save_sync_state(state, root)

    return {
        "found": len(manifest_paths),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "combination_usage": usage,
        "items": items,
        "owners": owners,
        "dry_run": dry_run,
    }


def import_all_stephen_packages(
    store,
    *,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return import_all_shared_packages(store, root=root, dry_run=dry_run, owners=[SHARED_OWNER])


def auto_sync_enabled() -> bool:
    return os.environ.get("SHARED_LIBRARY_AUTO_SYNC", "1").strip().lower() not in ("0", "false", "no")


def auto_sync_interval_minutes() -> int:
    try:
        return max(1, int(os.environ.get("SHARED_LIBRARY_AUTO_SYNC_MINUTES", "10")))
    except ValueError:
        return 10


def _sync_is_due(state: dict[str, Any], *, interval_minutes: int | None = None) -> bool:
    interval = interval_minutes if interval_minutes is not None else auto_sync_interval_minutes()
    last = state.get("last_auto_sync_at") or state.get("last_pull_at") or state.get("last_import_at")
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


def pull_and_import(
    store,
    *,
    skip_pull: bool = False,
    dry_run: bool = False,
    fetch_git: bool = True,
) -> dict[str, Any]:
    """Pull Stephen packages from GitHub (scoped) and import into production library + site."""
    from discovery.shared_library_git import git_repo_status, pull_shared_library

    pull_result = None
    pull_warning = None
    if not skip_pull:
        try:
            pull_result = pull_shared_library(dry_run=dry_run)
            if not pull_result.get("ok"):
                pull_warning = pull_result.get("message") or "Git pull did not complete"
            elif pull_result.get("warnings"):
                pull_warning = "; ".join(str(w) for w in pull_result["warnings"])
            if not dry_run and pull_result and pull_result.get("ok"):
                state = load_sync_state()
                state["last_pull_at"] = now_iso()
                save_sync_state(state)
        except RuntimeError as exc:
            pull_warning = str(exc)

    import_result = import_all_shared_packages(store, dry_run=dry_run)
    git_status = git_repo_status(fetch=fetch_git and not dry_run)

    return {
        "pull": pull_result,
        "pull_warning": pull_warning,
        "import": import_result,
        "git": git_status,
        "status": sync_status(git=git_status),
    }


def maybe_auto_pull_import(store, *, force: bool = False) -> dict[str, Any] | None:
    """Run pull+import when auto-sync is enabled and interval elapsed."""
    if not force and not auto_sync_enabled():
        return None
    state = load_sync_state()
    if not force and not _sync_is_due(state):
        return None
    result = pull_and_import(store, fetch_git=not force)
    state = load_sync_state()
    state["last_auto_sync_at"] = now_iso()
    save_sync_state(state)
    result["auto_sync"] = True
    result["skipped"] = False
    return result


def _owner_sync_stats(root: Path, state: dict[str, Any]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    imports = state.get("imports") or {}
    for owner in SHARED_LIBRARY_OWNERS:
        base = root / "shared_library" / owner
        manifests = list(base.glob("*/manifest.json")) if base.is_dir() else []
        imports_for_owner = sum(1 for mid in imports if str(mid).startswith(f"{owner}:"))
        stats[owner] = {
            "packages_on_disk": len(manifests),
            "imports_recorded": imports_for_owner,
            "pending_import": max(0, len(manifests) - imports_for_owner),
        }
    return stats


def build_sync_health(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """One-glance verdict: videos imported + code not behind remote."""
    status = status or {}
    git = status.get("git") or {}
    pending = int(status.get("pending_import") or 0)
    behind = git.get("commits_behind")
    ahead = git.get("commits_ahead")
    library_ok = pending == 0
    code_behind = isinstance(behind, int) and behind > 0
    code_ahead = isinstance(ahead, int) and ahead > 0
    code_ok = not code_behind and not code_ahead
    if git.get("conflict"):
        label = "conflict"
        summary = str(git.get("code_sync_hint") or "code conflict — fix then re-sync")
    elif not library_ok and not code_ok:
        label = "behind"
        extra = f"code {behind} behind" if code_behind else f"code {ahead} not pushed"
        summary = f"{pending} video(s) waiting · {extra}"
    elif not library_ok:
        label = "library_behind"
        summary = f"{pending} shared video(s) not imported yet"
    elif code_behind:
        label = "code_behind"
        summary = f"code {behind} commit(s) behind GitHub"
    elif code_ahead:
        label = "code_ahead"
        summary = f"code {ahead} commit(s) not pushed to GitHub"
    else:
        label = "synced"
        summary = "code even on both GitHubs · videos imported"
    return {
        "ok": library_ok and code_ok and not git.get("conflict"),
        "label": label,
        "library_ok": library_ok,
        "code_ok": code_ok,
        "pending_import": pending,
        "commits_behind": behind,
        "commits_ahead": ahead,
        "summary": summary,
    }


def sync_health_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "shared_library" / "sync_health.json"


def write_sync_health(status: dict[str, Any], *, root: Path | None = None) -> Path:
    health = status.get("health") or build_sync_health(status)
    path = sync_health_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": now_iso(),
        **health,
        "last_import_at": status.get("last_import_at"),
        "last_pull_at": status.get("last_pull_at"),
        "last_auto_sync_at": status.get("last_auto_sync_at"),
        "owners": status.get("owners"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def sync_status(root: Path | None = None, *, git: dict[str, Any] | None = None) -> dict[str, Any]:
    root = root or project_root()
    state = load_sync_state(root)
    owners = _owner_sync_stats(root, state)
    packages_on_disk = sum(item["packages_on_disk"] for item in owners.values())
    imports_recorded = len(state.get("imports", {}))
    pending_import = sum(item["pending_import"] for item in owners.values())
    if git is None:
        try:
            from discovery.shared_library_git import git_repo_status

            git = git_repo_status(fetch=False)
        except Exception:
            git = {}
    status = {
        "owner": export_owner() or SHARED_OWNER,
        "export_owner": export_owner(),
        "owners": owners,
        "packages_on_disk": packages_on_disk,
        "imports_recorded": imports_recorded,
        "pending_import": pending_import,
        "exports_recorded": len(state.get("exports", {})),
        "last_import_at": state.get("last_import_at"),
        "last_pull_at": state.get("last_pull_at"),
        "last_push_at": state.get("last_push_at"),
        "last_auto_sync_at": state.get("last_auto_sync_at"),
        "auto_sync_enabled": auto_sync_enabled(),
        "auto_sync_interval_minutes": auto_sync_interval_minutes(),
        "auto_push_enabled": auto_push_enabled(),
        "export_enabled": export_enabled(),
        "git": git,
        "last_code_pull_at": state.get("last_code_pull_at"),
        "brother_auto_pull_enabled": _brother_auto_pull_enabled(),
        "brother_auto_pull_interval_minutes": _brother_auto_pull_interval_minutes(),
    }


def _brother_auto_pull_enabled() -> bool:
    try:
        from discovery.brother_code_sync import auto_pull_enabled

        return auto_pull_enabled()
    except Exception:
        return False


def _brother_auto_pull_interval_minutes() -> int:
    try:
        from discovery.brother_code_sync import auto_pull_interval_minutes

        return auto_pull_interval_minutes()
    except Exception:
        return 60
