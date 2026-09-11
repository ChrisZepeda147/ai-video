"""Render a new Short from existing audio + visual pack components."""

from __future__ import annotations

import json
import math
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.auto_register import _components_from_job_dir, _read_json3_transcript
from discovery.combinations import (
    _resolve_speaker,
    get_audio_component,
    get_visual_pack,
    normalize_owner,
    record_combination_usage,
)
from discovery.config import project_root
from discovery.production_library import get_video, register_video


def _scripts_path() -> None:
    scripts = Path(__file__).resolve().parent.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))


def _resolve_caption_path(store, video_id: int, job_dir: Path) -> Path | None:
    for candidate in (
        job_dir / "audio" / "subs.en.json3",
        job_dir / "audio" / "subs.en.json",
    ):
        if candidate.is_file():
            return candidate
    row = store._conn.execute(
        """
        SELECT local_path FROM production_video_components
        WHERE video_id = ? AND component_type = 'caption'
        ORDER BY id LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    if row and row["local_path"]:
        path = project_root() / str(row["local_path"])
        if path.is_file():
            return path
    return None


def _parse_pack_meta(pack: dict[str, Any]) -> dict[str, Any]:
    raw = pack.get("metadata_json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _clip_parts(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.glob("*_part*.mp4"))


def _resolve_visual_clips_root(root: Path, pack: dict[str, Any], store) -> Path | None:
    clips_rel = pack.get("clips_root_path")
    if clips_rel:
        candidate = root / str(clips_rel)
        if _clip_parts(candidate):
            return candidate

    meta = _parse_pack_meta(pack)
    slug = str(meta.get("source_slug") or "").strip()
    if slug:
        job_clips = root / "downloads" / "motivational" / slug / "clips"
        if _clip_parts(job_clips):
            return job_clips

    source_video_id = pack.get("source_video_id")
    if source_video_id:
        rows = store._conn.execute(
            """
            SELECT local_path FROM production_video_components
            WHERE video_id = ? AND component_type = 'visual' AND local_path LIKE '%_part%.mp4'
            ORDER BY sort_order, id
            """,
            (int(source_video_id),),
        ).fetchall()
        if rows:
            first = root / str(rows[0]["local_path"] or "")
            if _clip_parts(first.parent):
                return first.parent
    return None


def _ensure_clips(clips_root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    parts = _clip_parts(clips_root)
    if not parts:
        raise FileNotFoundError(f"No clip parts in {clips_root}")
    for clip in parts:
        target = dest / clip.name
        if not target.exists():
            shutil.copy2(clip, target)


def _hydrate_visual_clips(
    *,
    root: Path,
    pack: dict[str, Any],
    clips_dir: Path,
    duration: float,
    beat_length: float,
) -> None:
    broll_ids = [str(item) for item in (pack.get("broll_ids") or []) if item]
    if not broll_ids:
        raise FileNotFoundError(
            f"Visual pack {pack.get('id')} has no clips folder and no broll_ids to re-download."
        )

    meta = _parse_pack_meta(pack)
    subject = str(
        pack.get("label")
        or pack.get("category")
        or meta.get("visual_style")
        or meta.get("broll_query")
        or "broll"
    )
    query = str(meta.get("visual_style") or meta.get("broll_query") or subject)

    _scripts_path()
    from build_clips_montage import min_unique_clips_needed
    from build_motivation_job import ensure_broll_clips

    needed = min_unique_clips_needed(
        duration=duration,
        segment_length=beat_length,
        layout="single",
    )
    clip_length = max(15, int(math.ceil(beat_length * 1.25)))
    clips_dir.mkdir(parents=True, exist_ok=True)
    ensure_broll_clips(
        jobs_root=root / "downloads" / "motivational",
        clips_dir=clips_dir,
        subject=subject,
        query=query,
        needed_clips=needed,
        clips_limit=max(6, len(broll_ids)),
        clip_length=clip_length,
        max_parts=2,
        min_views=0,
        min_duration=0,
        start_offset=0.0,
        use_vision=True,
        broll_ids=broll_ids,
        reuse_policy="allow",
    )
    if not _clip_parts(clips_dir):
        raise FileNotFoundError(
            f"Could not hydrate visual clips for pack {pack.get('id')} from broll_ids."
        )


def render_combination(
    store,
    *,
    owner: str,
    audio_component_id: int,
    visual_pack_id: int,
    audio_start_sec: float | None = None,
    audio_end_sec: float | None = None,
    segment_length: float | None = None,
    grade: bool = True,
    version_label: str | None = None,
    change_summary: str | None = None,
    force_usage: bool = False,
    slug: str | None = None,
) -> dict[str, Any]:
    """Combine existing audio + visual pack using build_motivation_job.render_job."""
    owner = normalize_owner(owner)
    audio = get_audio_component(store, audio_component_id)
    if not audio:
        raise ValueError(f"Audio component {audio_component_id} not found")

    pack = get_visual_pack(store, visual_pack_id)
    if not pack:
        raise ValueError(f"Visual pack {visual_pack_id} not found")

    root = project_root()
    audio_path = root / str(audio["local_path"])
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file missing: {audio_path}")

    parent_video_id = int(audio["video_id"])
    parent = get_video(store, parent_video_id)
    parent_slug = str(parent.get("slug") or f"video-{parent_video_id}") if parent else f"video-{parent_video_id}"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = slug or f"combo-{owner}-{audio_component_id}-{visual_pack_id}-{stamp}"
    job_dir = root / "downloads" / "motivational" / slug
    audio_dir = job_dir / "audio"
    clips_dir = job_dir / "clips"
    output_dir = job_dir / "output"
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    caption_src = _resolve_caption_path(store, parent_video_id, job_dir)
    speech_mp3 = audio_dir / "speech.mp3"
    captions = audio_dir / "subs.en.json3"

    _scripts_path()
    from build_clips_montage import probe_duration, segment_length_for_duration
    from build_motivation_job import render_job, shift_json3, trim_audio

    start = float(audio_start_sec if audio_start_sec is not None else (audio.get("start_sec") or 0.0))
    probed = float(probe_duration(audio_path))
    if audio_end_sec is not None and float(audio_end_sec) > start:
        duration = float(audio_end_sec) - start
    elif audio.get("end_sec") is not None and float(audio["end_sec"]) > start:
        duration = float(audio["end_sec"]) - start
    else:
        duration = probed - start if start > 0 else probed
    if duration <= 0:
        duration = probed

    beat_length = segment_length if segment_length is not None else segment_length_for_duration(duration)

    if audio_start_sec is not None or (audio.get("start_sec") and float(audio.get("start_sec") or 0) > 0):
        trim_audio(audio_path, speech_mp3, start=start, duration=duration)
        if caption_src and caption_src.is_file():
            if caption_src.suffix.lower() == ".json3":
                shift_json3(caption_src, captions, start=start, duration=duration)
            else:
                shutil.copy2(caption_src, captions)
        else:
            captions.write_text('{"events":[]}', encoding="utf-8")
    else:
        shutil.copy2(audio_path, speech_mp3)
        if caption_src and caption_src.is_file():
            shutil.copy2(caption_src, captions)
        else:
            captions.write_text('{"events":[]}', encoding="utf-8")

    clips_root = _resolve_visual_clips_root(root, pack, store)
    if clips_root:
        _ensure_clips(clips_root, clips_dir)
    else:
        _hydrate_visual_clips(
            root=root,
            pack=pack,
            clips_dir=clips_dir,
            duration=duration,
            beat_length=beat_length,
        )
    output = output_dir / f"{slug}-motivation.mp4"

    render_job(
        jobs_root=root / "downloads" / "motivational",
        clips_dir=clips_dir,
        audio=speech_mp3,
        captions=captions,
        output=output,
        duration=duration,
        segment_length=beat_length,
        seed=None,
        grade=grade,
        subject=str(pack.get("label") or pack.get("category") or ""),
    )

    from discovery.media_paths import is_complete_motivation_job, is_playable_file

    if not is_playable_file(output):
        raise ValueError(f"Combination render produced invalid output for {slug}")
    if not is_complete_motivation_job(root, slug, output_path=output):
        raise ValueError(
            f"Combination job {slug} is incomplete — needs speech audio, visual clips, and a real output file"
        )

    rel_output = output.relative_to(root).as_posix()
    speaker = _resolve_speaker(audio, store)
    if speaker == "Unknown":
        speaker = ""
    pack_label = str(pack.get("label") or pack.get("category") or "visual pack")
    title = f"{speaker} × {pack_label}".strip(" ×")
    transcript = _read_json3_transcript(captions) or (audio.get("transcript_segment") or "")

    components = _components_from_job_dir(job_dir, root)
    metadata = {
        "pipeline": "combination_render",
        "owner": owner,
        "audio_component_id": audio_component_id,
        "visual_pack_id": visual_pack_id,
        "parent_audio_video_id": parent_video_id,
        "broll_ids": pack.get("broll_ids") or [],
        "visual_style": pack.get("category"),
    }

    video = register_video(
        store,
        title=title[:200],
        slug=slug,
        speaker=speaker or None,
        podcast_source=speaker or None,
        source_url=audio.get("source_url"),
        source_platform="youtube" if audio.get("source_external_id") else None,
        source_external_id=audio.get("source_external_id"),
        source_start_sec=start if audio_start_sec is not None else audio.get("start_sec"),
        source_end_sec=(start + duration) if audio_start_sec is not None else audio.get("end_sec"),
        transcript_segment=transcript or None,
        topic="motivation",
        parent_video_id=parent_video_id,
        version_label=version_label or f"{pack.get('display_id') or visual_pack_id}",
        change_summary=change_summary or f"Combination render for {owner}: audio {audio_component_id} + pack {visual_pack_id}",
        final_output_path=rel_output,
        duration_sec=duration,
        components=components,
        metadata=metadata,
        copy_final_to_library=True,
    )

    job_json = {
        "slug": slug,
        "owner": owner,
        "audio_component_id": audio_component_id,
        "visual_pack_id": visual_pack_id,
        "parent_video_id": parent_video_id,
        "audio_duration": duration,
        "broll_ids": pack.get("broll_ids") or [],
        "output": rel_output,
    }
    (job_dir / "job.json").write_text(json.dumps(job_json, indent=2), encoding="utf-8")

    usage = record_combination_usage(
        store,
        owner=owner,
        audio_component_id=audio_component_id,
        visual_pack_id=visual_pack_id,
        rendered_video_id=int(video["id"]),
        audio_start_sec=start,
        audio_end_sec=start + duration,
        force=force_usage,
    )

    try:
        from discovery.auto_register import sync_register_best_effort

        sync_register_best_effort(slug=slug, topic="motivation")
    except Exception:
        pass

    try:
        from discovery.shared_library import export_stephen_after_register

        export_stephen_after_register(slug=slug, video=video, store=store)
    except Exception:
        pass

    return {
        "video": video,
        "usage": usage,
        "output_path": rel_output,
        "slug": slug,
        "owner": owner,
    }
