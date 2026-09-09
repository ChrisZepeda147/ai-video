"""Generation job creation, Cursor handoff, and idempotent import."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import (
    generation_jobs_dir,
    visual_aspect_ratio,
    visual_image_duration,
    visual_min_height,
    visual_min_width,
)
from discovery.models import GenerationJob
from discovery.visual_quality import run_quality_checks

ALLOWED_ORIGIN_TYPES = {
    "reference",
    "concept",
    "source_media",
    "original_story",
    "freeform",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}


@dataclass
class JobOutputSpec:
    filename: str
    asset_type: str
    prompt: str
    variant_index: int


@dataclass
class GenerationJobResult:
    job: GenerationJob
    outputs: list[JobOutputSpec] = field(default_factory=list)


def _next_job_key(store) -> str:
    row = store._conn.execute("SELECT COUNT(*) AS cnt FROM generation_jobs").fetchone()
    n = int(row["cnt"]) + 1
    return f"job_{n:06d}"


def _style_modifiers(style: str | None) -> str:
    style = (style or "cinematic").lower()
    mapping = {
        "luxury": "beautiful realistic luxury, supercars, mansions, city nights, penthouses, watches, jets",
        "horror": "dark houses, hallways, foggy roads, woods, bedrooms, basements, dread",
        "relationship": "night driving, rainy windows, phones, lonely apartments, empty tables",
        "motivation": "people working late, gym discipline, sunrise grind, focused ambition",
    }
    for key, value in mapping.items():
        if key in style:
            return value
    return style


def _build_prompts(
    *,
    prompt_summary: str,
    style: str | None,
    niche: str | None,
    image_count: int,
    video_count: int,
    context: dict[str, Any],
) -> list[JobOutputSpec]:
    mood = context.get("mood") or context.get("visual_mood") or "cinematic"
    genre = context.get("genre") or niche or "general"
    style_hint = _style_modifiers(style)
    outputs: list[JobOutputSpec] = []
    idx = 1
    for i in range(image_count):
        prompt = (
            f"{prompt_summary}. Style: {style_hint}. Mood: {mood}. Genre: {genre}. "
            f"Vertical 9:16 cinematic still. Original production asset — not scraped footage. "
            f"Variant {i + 1}."
        )
        outputs.append(
            JobOutputSpec(
                filename=f"image_{idx:02d}.png",
                asset_type="image",
                prompt=prompt,
                variant_index=idx,
            )
        )
        idx += 1
    for i in range(video_count):
        prompt = (
            f"{prompt_summary}. Style: {style_hint}. Mood: {mood}. Genre: {genre}. "
            f"Vertical 9:16 moving clip, subtle camera motion. Original AI video — not scraped footage. "
            f"Clip {i + 1}."
        )
        outputs.append(
            JobOutputSpec(
                filename=f"video_{idx:02d}.mp4",
                asset_type="video",
                prompt=prompt,
                variant_index=idx,
            )
        )
        idx += 1
    return outputs


def _gather_context(store, *, reference_id, concept_id, source_media_id) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    if concept_id:
        concept = store.get_concept(concept_id)
        if concept:
            ctx.update(concept)
            ctx["prompt_summary"] = concept.get("visual_premise") or concept.get("title")
    if reference_id:
        analysis = store.get_latest_analysis(reference_id)
        if analysis:
            ctx["visual_mood"] = analysis.visual_mood
            ctx["genre"] = analysis.genre
    if source_media_id:
        source = store.get_source_media(source_media_id)
        if source:
            ctx["prompt_summary"] = source.title
            if source.transcript:
                ctx["transcript_snippet"] = source.transcript[:300]
    return ctx


def create_generation_job(
    store,
    *,
    origin_type: str,
    prompt_summary: str,
    image_count: int = 0,
    video_count: int = 0,
    style: str | None = None,
    aspect_ratio: str | None = None,
    niche: str | None = None,
    reference_id: int | None = None,
    concept_id: int | None = None,
    source_media_id: int | None = None,
) -> GenerationJobResult:
    if origin_type not in ALLOWED_ORIGIN_TYPES:
        raise ValueError(f"Invalid origin_type: {origin_type}")
    if image_count < 0 or video_count < 0:
        raise ValueError("Counts must be non-negative")
    if image_count == 0 and video_count == 0:
        raise ValueError("At least one image or video must be requested")

    ctx = _gather_context(
        store,
        reference_id=reference_id,
        concept_id=concept_id,
        source_media_id=source_media_id,
    )
    if not prompt_summary:
        prompt_summary = ctx.get("prompt_summary") or ctx.get("title") or "Original cinematic visual"
    aspect = aspect_ratio or visual_aspect_ratio()

    job_key = _next_job_key(store)
    job_dir = generation_jobs_dir() / job_key
    images_dir = job_dir / "output" / "images"
    videos_dir = job_dir / "output" / "videos"
    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    outputs = _build_prompts(
        prompt_summary=prompt_summary,
        style=style,
        niche=niche,
        image_count=image_count,
        video_count=video_count,
        context=ctx,
    )

    job_payload = {
        "job_key": job_key,
        "origin_type": origin_type,
        "reference_id": reference_id,
        "concept_id": concept_id,
        "source_media_id": source_media_id,
        "image_count": image_count,
        "video_count": video_count,
        "style": style,
        "aspect_ratio": aspect,
        "niche": niche,
        "prompt_summary": prompt_summary,
        "width": visual_min_width(),
        "height": visual_min_height(),
        "outputs": [
            {
                "filename": spec.filename,
                "asset_type": spec.asset_type,
                "prompt": spec.prompt,
                "variant_index": spec.variant_index,
                "expected_path": str(
                    (images_dir if spec.asset_type == "image" else videos_dir) / spec.filename
                ),
            }
            for spec in outputs
        ],
    }

    job_json_path = job_dir / "job.json"
    cursor_prompt_path = job_dir / "CURSOR_GENERATION_PROMPT.md"
    job_json_path.write_text(json.dumps(job_payload, indent=2), encoding="utf-8")

    cursor_lines = [
        f"# Cursor generation job: {job_key}",
        "",
        f"**Origin:** {origin_type}",
        f"**Style:** {style or 'cinematic'}",
        f"**Aspect:** {aspect}",
        f"**Images:** {image_count} | **Videos:** {video_count}",
        "",
        "## Instructions",
        "",
        "1. Generate each output below using available Cursor image/video capabilities.",
        "2. Save files to the exact paths under `output/images/` or `output/videos/`.",
        "3. Keep visual mood/topic/emotion consistent across the set.",
        "4. Do NOT illustrate every spoken sentence — match mood, genre, and aspiration.",
        "5. After saving all files, run import via API or CLI.",
        "",
        "## Outputs",
        "",
    ]
    for spec in outputs:
        subdir = "images" if spec.asset_type == "image" else "videos"
        cursor_lines.extend(
            [
                f"### {spec.filename} ({spec.asset_type})",
                f"Save to: `output/{subdir}/{spec.filename}`",
                "",
                spec.prompt,
                "",
            ]
        )
    cursor_prompt_path.write_text("\n".join(cursor_lines), encoding="utf-8")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    job_id = store.create_generation_job(
        job_key=job_key,
        origin_type=origin_type,
        image_count=image_count,
        video_count=video_count,
        aspect_ratio=aspect,
        style=style,
        niche=niche,
        prompt_summary=prompt_summary,
        reference_id=reference_id,
        concept_id=concept_id,
        source_media_id=source_media_id,
        job_json_path=str(job_json_path),
        cursor_prompt_path=str(cursor_prompt_path),
        output_dir=str(job_dir),
        status="pending",
        created_at=now,
    )

    job = store.get_generation_job(job_id)
    if not job:
        raise RuntimeError("Failed to load created generation job")
    return GenerationJobResult(job=job, outputs=outputs)


def list_pending_generation_jobs(store, *, limit: int = 50) -> list[GenerationJob]:
    return store.list_generation_jobs(status="pending", limit=limit)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_generation_job(store, job_id: int) -> dict[str, Any]:
    """Import completed job outputs into visual_assets (idempotent)."""
    job = store.get_generation_job(job_id)
    if not job:
        raise ValueError(f"Generation job {job_id} not found")
    if not job.output_dir:
        raise ValueError("Job has no output directory")

    job_dir = Path(job.output_dir)
    job_json_path = job_dir / "job.json"
    if not job_json_path.is_file():
        raise ValueError(f"Missing job.json at {job_json_path}")

    payload = json.loads(job_json_path.read_text(encoding="utf-8"))
    imported = 0
    skipped = 0
    failed: list[str] = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    family = "freeform"
    if job.concept_id:
        concept = store.get_concept(job.concept_id)
        if concept:
            family = concept.get("variation_family") or family

    for item in payload.get("outputs", []):
        expected = Path(item["expected_path"])
        if not expected.is_file():
            alt_dir = job_dir / "output" / ("images" if item["asset_type"] == "image" else "videos")
            expected = alt_dir / item["filename"]
        if not expected.is_file():
            failed.append(f"Missing file: {item['filename']}")
            continue

        local_path = str(expected.resolve())
        existing = store.find_visual_asset_by_job_path(job_id, local_path)
        if existing:
            skipped += 1
            continue

        sha = _file_sha256(expected)
        if store.find_visual_asset_by_sha(sha):
            skipped += 1
            continue

        asset_id = store.create_visual_asset(
            concept_id=job.concept_id,
            reference_id=job.reference_id,
            generation_job_id=job_id,
            source_media_id=job.source_media_id,
            niche=job.niche,
            variation_family=family,
            asset_type=item["asset_type"],
            provider="cursor_handoff",
            model="pending",
            prompt=item["prompt"],
            brief_json=json.dumps({"job_key": job.job_key, "filename": item["filename"]}),
            local_path=local_path,
            variant_index=int(item.get("variant_index") or 1),
            status="generated",
        )
        store.update_visual_asset_after_generation(
            asset_id,
            local_path=local_path,
            duration_seconds=visual_image_duration() if item["asset_type"] == "image" else 3.0,
            width=visual_min_width(),
            height=visual_min_height(),
            aspect_ratio=job.aspect_ratio,
            generated_at=now,
            status="generated",
        )
        store.update_visual_asset_sha(asset_id, sha)
        asset_row = store.get_visual_asset_dict(asset_id)
        qc = run_quality_checks(store, asset_row or {})
        if qc.passed:
            store.update_visual_asset_status(asset_id, "review")
        else:
            store.update_visual_asset_status(asset_id, "auto_rejected", reject_reason=qc.reason)
        imported += 1

    status = "imported" if not failed else "completed"
    store.update_generation_job_status(
        job_id,
        status=status,
        imported_at=now,
        completed_at=now,
        error_message="; ".join(failed) if failed else None,
    )
    return {
        "job_id": job_id,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
    }
