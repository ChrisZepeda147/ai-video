"""Auto-register completed production videos — call from every pipeline on success."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from discovery.config import default_db_path, project_root
from discovery.production_library import get_video, register_video

logger = logging.getLogger(__name__)


def _scripts_path() -> None:
    scripts = Path(__file__).resolve().parent.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))


def find_video_by_slug(store, slug: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        "SELECT id FROM production_library_videos WHERE slug = ? ORDER BY id DESC LIMIT 1",
        (slug,),
    ).fetchone()
    if not row:
        return None
    return get_video(store, int(row["id"]))


def find_video_by_output_path(store, output_path: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        "SELECT id FROM production_library_videos WHERE final_output_path = ? LIMIT 1",
        (output_path.replace("\\", "/"),),
    ).fetchone()
    if not row:
        return None
    return get_video(store, int(row["id"]))


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_url_txt(job_dir: Path) -> str:
    path = job_dir / "url.txt"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _read_ytdlp_info(job_dir: Path) -> dict[str, Any]:
    audio = job_dir / "audio"
    if not audio.is_dir():
        return {}
    for info_path in sorted(audio.glob("*.info.json")):
        try:
            return json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return {}


def _motivation_payload_fallback(job_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    speech_url = _read_url_txt(job_dir)
    if speech_url:
        payload["speech_url"] = speech_url
    info = _read_ytdlp_info(job_dir)
    if info:
        payload["speech_title"] = info.get("title") or ""
        payload["speech_id"] = info.get("id") or ""
        title = str(info.get("title") or "").lower()
        channel = str(info.get("channel") or "")
        if "tate" in title or "tate" in channel.lower():
            payload["speaker"] = "Andrew Tate"
        elif channel:
            payload["speaker"] = channel
    clips_dir = job_dir / "clips"
    if clips_dir.is_dir():
        broll_ids: list[str] = []
        for info_path in sorted(clips_dir.glob("*_source.info.json")):
            try:
                clip_info = json.loads(info_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            clip_id = clip_info.get("id")
            if clip_id and clip_id not in broll_ids:
                broll_ids.append(str(clip_id))
        if broll_ids:
            payload["broll_ids"] = broll_ids
    return payload


def _probe_duration_sec(path: Path) -> float | None:
    try:
        from toolchain_env import resolve_tool

        ffprobe = resolve_tool("ffprobe")
    except ImportError:
        ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return None
    try:
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(probe.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _read_json3_transcript(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        _scripts_path()
        from build_stills_slideshow import parse_json3_words

        words = parse_json3_words(path, start=0.0, duration=1_000_000.0)
        return " ".join(text for _, _, text in words if text).strip()
    except Exception:
        return ""


def _components_from_job_dir(job_dir: Path, root: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    audio = job_dir / "audio" / "speech.mp3"
    if audio.is_file():
        components.append({"component_type": "audio", "local_path": _rel(audio, root), "label": "Speech audio"})
    caps = job_dir / "audio" / "subs.en.json3"
    if caps.is_file():
        components.append({"component_type": "caption", "local_path": _rel(caps, root), "label": "Word captions"})
    clips_dir = job_dir / "clips"
    if clips_dir.is_dir():
        for index, clip in enumerate(sorted(clips_dir.glob("*.mp4"))):
            components.append(
                {
                    "component_type": "visual",
                    "local_path": _rel(clip, root),
                    "label": clip.name,
                    "sort_order": index,
                }
            )
    stills_dir = job_dir / "stills"
    if stills_dir.is_dir():
        for index, still in enumerate(sorted(stills_dir.glob("*.*"))):
            if still.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                components.append(
                    {
                        "component_type": "visual",
                        "local_path": _rel(still, root),
                        "label": still.stem,
                        "sort_order": 100 + index,
                    }
                )
    return components


def auto_register_motivation_job(
    store,
    *,
    slug: str,
    root: Path | None = None,
    creation_prompt: str | None = None,
    command_job_id: int | None = None,
    parent_video_id: int | None = None,
    change_summary: str | None = None,
    visual_style: str | None = None,
    topic: str | None = None,
) -> dict[str, Any] | None:
    """Register a build_motivation_job.py output with all available components."""
    root = root or project_root()
    job_dir = root / "downloads" / "motivational" / slug
    output_dir = job_dir / "output"
    output = output_dir / f"{slug}-motivation.mp4"
    if not output.is_file() and output_dir.is_dir():
        candidates = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        output = candidates[0] if candidates else output
    if not output.is_file():
        logger.warning("Motivation output missing: %s", output_dir)
        return None

    rel_output = _rel(output, root)
    existing = find_video_by_slug(store, slug) or find_video_by_output_path(store, rel_output)
    if existing:
        logger.info("Already registered: Video %s (%s)", existing["id"], slug)
        return existing

    payload: dict[str, Any] = {}
    job_json = job_dir / "job.json"
    if job_json.is_file():
        payload = json.loads(job_json.read_text(encoding="utf-8"))
    fallback = _motivation_payload_fallback(job_dir)
    if fallback:
        payload = {**fallback, **payload}

    speaker = payload.get("speaker") or ""
    speech_url = payload.get("speech_url") or ""
    speech_id = payload.get("speech_id") or ""
    broll_query = payload.get("broll_query") or payload.get("speech_query") or ""
    duration = payload.get("audio_duration") or _probe_duration_sec(output)

    caps = job_dir / "audio" / "subs.en.json3"
    transcript = _read_json3_transcript(caps)
    title = payload.get("speech_title") or slug.replace("-", " ").title()

    components = _components_from_job_dir(job_dir, root)
    if speech_url:
        components.insert(
            0,
            {
                "component_type": "source",
                "url": speech_url,
                "label": f"YouTube {speech_id}" if speech_id else "Speech source",
            },
        )

    metadata: dict[str, Any] = {"pipeline": "build_motivation_job", "broll_ids": payload.get("broll_ids") or []}
    if visual_style:
        metadata["visual_style"] = visual_style
    if broll_query:
        metadata["broll_query"] = broll_query

    video = register_video(
        store,
        title=str(title),
        slug=slug,
        speaker=str(speaker) if speaker else None,
        podcast_source=str(speaker) if speaker else None,
        source_url=speech_url or None,
        source_platform="youtube" if speech_id else None,
        source_external_id=speech_id or None,
        transcript_segment=transcript or None,
        topic=topic or _infer_topic(slug, broll_query),
        creation_prompt=creation_prompt,
        creation_command_job_id=command_job_id,
        parent_video_id=parent_video_id,
        change_summary=change_summary,
        final_output_path=rel_output,
        duration_sec=float(duration) if duration else None,
        components=components,
        metadata=metadata,
        copy_final_to_library=True,
    )
    logger.info("Registered Video %s: %s", video.get("id"), slug)
    return video


def auto_register_final_output(
    store,
    *,
    final_path: str | Path,
    slug: str | None = None,
    title: str | None = None,
    speaker: str | None = None,
    topic: str | None = None,
    hook: str | None = None,
    source_url: str | None = None,
    transcript: str | None = None,
    job_dir: str | Path | None = None,
    pipeline: str = "unknown",
    creation_prompt: str | None = None,
    command_job_id: int | None = None,
    parent_video_id: int | None = None,
    change_summary: str | None = None,
    visual_style: str | None = None,
    metadata: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Generic auto-register for any pipeline that produced a final MP4."""
    root = root or project_root()
    path = Path(final_path)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        logger.warning("Final output not found: %s", path)
        return None

    rel_output = _rel(path, root)
    slug = slug or path.parent.parent.name if path.parent.parent.name not in {"output", "production"} else path.stem
    existing = find_video_by_slug(store, slug) if slug else None
    if not existing:
        existing = find_video_by_output_path(store, rel_output)
    if existing:
        return existing

    components: list[dict[str, Any]] = []
    if job_dir:
        components = _components_from_job_dir(Path(job_dir), root)

    meta = {"pipeline": pipeline, **(metadata or {})}
    if visual_style:
        meta["visual_style"] = visual_style

    return register_video(
        store,
        title=title or slug.replace("-", " ").title(),
        slug=slug,
        speaker=speaker,
        topic=topic,
        hook=hook,
        source_url=source_url,
        transcript_segment=transcript,
        creation_prompt=creation_prompt,
        creation_command_job_id=command_job_id,
        parent_video_id=parent_video_id,
        change_summary=change_summary,
        final_output_path=rel_output,
        components=components,
        metadata=meta,
        copy_final_to_library=True,
    )


def _infer_topic(slug: str, broll_query: str) -> str | None:
    text = f"{slug} {broll_query}".lower()
    for word in ("discipline", "motivation", "consistency", "mindset", "success", "wealth"):
        if word in text:
            return word
    return None


def sync_register_best_effort(**kwargs: Any) -> dict[str, Any] | None:
    """Entry point pipelines call — never raises."""
    db = kwargs.pop("db_path", None) or default_db_path()
    if not Path(db).parent.exists() and not Path(db).is_file():
        return None
    try:
        from discovery.store import DiscoveryStore

        store = DiscoveryStore(db)
        try:
            slug = kwargs.get("slug")
            if slug:
                return auto_register_motivation_job(store, slug=str(slug), **{k: v for k, v in kwargs.items() if k != "slug"})
            return auto_register_final_output(store, **kwargs)
        finally:
            store.close()
    except Exception as exc:
        logger.warning("Auto-register skipped: %s", exc)
        return None
