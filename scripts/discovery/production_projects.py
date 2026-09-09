"""Production project lifecycle — draft through approved Short."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discovery.acquire import acquire_source_media, clip_source_segment
from discovery.config import project_root
from discovery.production_risk import risk_explanations_json, score_finished_short
from discovery.render_short import render_short
from discovery.timeline import plan_timeline, timeline_to_json
from discovery.transcription.factory import build_transcription_provider

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import content_reuse  # noqa: E402

ALLOWED_STATUSES = {"draft", "ready", "rendering", "rendered", "review", "approved", "rejected", "failed"}
FORMAT_PROFILES = {"audio_visuals", "source_video_visuals", "original_story"}


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "short"


@dataclass
class ProjectResult:
    project_id: int
    slug: str
    status: str
    output_path: str | None = None


def create_production_project(
    store,
    *,
    title: str,
    niche: str | None = None,
    origin_type: str = "reference",
    reference_id: int | None = None,
    source_media_id: int | None = None,
    source_segment_id: int | None = None,
    concept_id: int | None = None,
    format_profile: str = "audio_visuals",
    hook_text: str | None = None,
    caption_preset: str = "viral_bold",
) -> ProjectResult:
    if format_profile not in FORMAT_PROFILES:
        raise ValueError(f"Invalid format_profile: {format_profile}")
    slug = slugify(title)
    existing = store.get_production_project_by_slug(slug)
    if existing:
        slug = f"{slug}-{existing.id + 1}"
    if source_media_id and not reference_id:
        source = store.get_source_media(source_media_id)
        if source and source.reference_id:
            reference_id = source.reference_id
    if format_profile == "original_story":
        origin_type = "original"

    project_id = store.create_production_project(
        slug=slug,
        title=title,
        niche=niche,
        origin_type=origin_type,
        reference_id=reference_id,
        source_media_id=source_media_id,
        source_segment_id=source_segment_id,
        concept_id=concept_id,
        format_profile=format_profile,
        hook_text=hook_text,
        caption_preset=caption_preset,
    )
    return ProjectResult(project_id=project_id, slug=slug, status="draft")


def acquire_for_project(store, source_media_id: int) -> dict[str, Any]:
    return acquire_source_media(store, source_media_id).__dict__


def transcribe_source(store, source_media_id: int, *, provider=None) -> Any:
    from discovery.source_media import transcribe_source_media_with_asr

    return transcribe_source_media_with_asr(store, source_media_id, provider=provider)


def build_project_timeline(
    store,
    project_id: int,
    *,
    visual_asset_ids: list[int] | None = None,
    duration_sec: float | None = None,
    pacing: str = "balanced",
) -> dict[str, Any]:
    project = store.get_production_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    if visual_asset_ids:
        store.set_project_visuals(project_id, visual_asset_ids)

    assets = store.list_project_visual_assets(project_id)
    if not assets:
        raise ValueError("Project needs approved visual assets")

    source_path = None
    audio_path = None
    dur = duration_sec
    transcript_json = None

    if project.source_segment_id:
        seg = store.get_source_segment(project.source_segment_id)
        if seg and seg.local_path:
            source_path = seg.local_path
            audio_path = seg.local_path
            if seg.end_sec and seg.start_sec is not None:
                dur = dur or (seg.end_sec - seg.start_sec)
    elif project.source_media_id:
        source = store.get_source_media(project.source_media_id)
        if source:
            transcript_json = source.transcript_json
            audio_path = source.local_path
            if source.duration_sec:
                dur = dur or source.duration_sec

    if not dur:
        dur = 30.0

    transcript_segments = []
    if transcript_json:
        try:
            payload = json.loads(transcript_json)
            transcript_segments = payload.get("segments", [])
        except json.JSONDecodeError:
            pass

    timeline = plan_timeline(
        duration_sec=dur,
        format_profile=project.format_profile,
        visual_assets=assets,
        transcript_segments=transcript_segments,
        source_segment_path=source_path,
        pacing=pacing,
    )
    store.update_production_project_timeline(project_id, timeline_to_json(timeline), status="ready")
    return timeline


def render_project(store, project_id: int) -> ProjectResult:
    project = store.get_production_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    if not project.timeline_json:
        raise ValueError("Project has no timeline — build timeline first")

    store.update_production_project_status(project_id, "rendering")
    timeline = json.loads(project.timeline_json)

    audio_path = None
    transcript_segments = []
    if project.source_segment_id:
        seg = store.get_source_segment(project.source_segment_id)
        if seg:
            audio_path = seg.local_path
    elif project.source_media_id:
        source = store.get_source_media(project.source_media_id)
        if source:
            audio_path = source.local_path
            if source.transcript_json:
                try:
                    transcript_segments = json.loads(source.transcript_json).get("segments", [])
                except json.JSONDecodeError:
                    pass

    try:
        result = render_short(
            slug=project.slug,
            timeline=timeline,
            audio_path=audio_path,
            caption_preset=project.caption_preset or "viral_bold",
            hook_text=project.hook_text,
            transcript_segments=transcript_segments,
        )
        dur = result.duration_sec
        risk = score_finished_short(
            store,
            project_id=project_id,
            source_media_id=project.source_media_id,
            format_profile=project.format_profile,
            timeline=timeline,
            source_duration=dur,
        )
        store.update_production_project_rendered(
            project_id,
            output_path=result.output_path,
            duration_sec=dur,
            monetization_confidence=risk.monetization_confidence,
            rights_confidence=risk.rights_confidence,
            reuse_confidence=risk.reuse_confidence,
            risk_explanations_json=risk_explanations_json(risk),
            status="review",
        )
        return ProjectResult(
            project_id=project_id,
            slug=project.slug,
            status="review",
            output_path=result.output_path,
        )
    except Exception as exc:
        store.update_production_project_status(project_id, "failed", error_message=str(exc))
        raise


def approve_project(store, project_id: int) -> ProjectResult:
    """Approve finished Short and mark source globally used (once)."""
    project = store.get_production_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    if project.status == "approved":
        return ProjectResult(
            project_id=project_id,
            slug=project.slug,
            status="approved",
            output_path=project.output_path,
        )

    if project.status not in {"review", "rendered"}:
        raise ValueError(f"Cannot approve project in status {project.status}")

    if project.source_media_id:
        source = store.get_source_media(project.source_media_id)
        if source and not source.actually_used_in_content:
            store.mark_source_media_used(project.source_media_id)
            if source.external_id:
                content_reuse.register_video(
                    youtube_id=source.external_id,
                    file_path=Path(project.output_path) if project.output_path else None,
                    title=project.title,
                    root=project_root(),
                )

    store.update_production_project_status(project_id, "approved")
    return ProjectResult(
        project_id=project_id,
        slug=project.slug,
        status="approved",
        output_path=project.output_path,
    )


def reject_project(store, project_id: int) -> ProjectResult:
    project = store.get_production_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    store.update_production_project_status(project_id, "rejected")
    return ProjectResult(project_id=project_id, slug=project.slug, status="rejected")


def send_project_to_review(store, project_id: int) -> ProjectResult:
    project = store.get_production_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    if not project.output_path:
        raise ValueError("Project has no rendered output to review")
    store.update_production_project_status(project_id, "review")
    return ProjectResult(
        project_id=project_id,
        slug=project.slug,
        status="review",
        output_path=project.output_path,
    )
