"""Convert discovery store rows to API models."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from discovery.config import project_root  # noqa: E402
from discovery.models import (  # noqa: E402
    Concept,
    GenerationJob,
    ReferenceAnalysis,
    SourceMedia,
    TopReference,
    VisualAsset,
)
from discovery.store import DiscoveryStore  # noqa: E402

from api.schemas import (  # noqa: E402
    AnalysisItem,
    ConceptItem,
    GenerationJobItem,
    ReferenceItem,
    RiskScoresItem,
    ReuseReportItem,
    SourceMediaItem,
    VisualAssetItem,
    WorkbenchCandidateItem,
    reference_item_from_store,
)


def local_path_to_media_url(local_path: str | None) -> str | None:
    if not local_path:
        return None
    try:
        rel = Path(local_path).resolve().relative_to(project_root().resolve())
        return f"/media/{rel.as_posix()}"
    except ValueError:
        return None


def top_to_reference_item(store: DiscoveryStore, top: TopReference) -> ReferenceItem:
    ref_id = int(top.reference.id)
    usage = store.get_reference_usage(ref_id)
    analysis_count = int(
        store._conn.execute(
            "SELECT COUNT(*) FROM reference_analyses WHERE reference_id = ?",
            (ref_id,),
        ).fetchone()[0]
    )
    row: dict[str, Any] = {
        "reference": top.reference,
        "metrics": top.metrics,
        "niches": top.niches,
        "concepts_generated": usage["concepts_generated"],
        "concepts_approved": usage["concepts_approved"],
        "exhausted": usage["exhausted"],
        "has_analysis": analysis_count > 0,
        "analysis_count": analysis_count,
    }
    return reference_item_from_store(row)


def analysis_to_item(analysis: ReferenceAnalysis, *, cached: bool = False) -> AnalysisItem:
    payload = analysis.analysis_json or {}
    observed = payload.get("observed") or {}
    inferred = payload.get("inferred") or {}
    transferable = analysis.transferable_patterns or payload.get("transferable_patterns")
    avoid = analysis.avoid_copying or payload.get("avoid_copying")
    if isinstance(transferable, list):
        transferable = "; ".join(str(x) for x in transferable)
    if isinstance(avoid, list):
        avoid = "; ".join(str(x) for x in avoid)
    return AnalysisItem(
        id=analysis.id,
        reference_id=analysis.reference_id,
        analyzed_at=analysis.analyzed_at,
        provider=analysis.provider,
        model=analysis.model,
        analysis_version=analysis.analysis_version,
        observed=observed if isinstance(observed, dict) else {},
        inferred=inferred if isinstance(inferred, dict) else {},
        hook_type=analysis.hook_type,
        emotional_trigger=analysis.emotional_trigger,
        pacing_style=analysis.pacing_style,
        story_structure=analysis.story_structure,
        visual_mood=analysis.visual_mood,
        transferable_patterns=str(transferable or ""),
        avoid_copying=str(avoid or ""),
        analysis_json=payload if isinstance(payload, dict) else {},
        cached=cached,
    )


def concept_to_item(store: DiscoveryStore, concept: Concept) -> ConceptItem:
    ref = store.get_reference_by_id(concept.reference_id)
    return ConceptItem(
        id=concept.id,
        reference_id=concept.reference_id,
        reference_title=ref.title if ref else None,
        reference_virality_score=ref.virality_score if ref else None,
        analysis_id=concept.analysis_id,
        niche=concept.niche,
        title=concept.title,
        hook_idea=concept.hook_idea,
        visual_premise=concept.visual_premise,
        setting=concept.setting,
        subject=concept.subject,
        camera_movement=concept.camera_movement,
        mood=concept.mood,
        story_premise=concept.story_premise,
        variation_family=concept.variation_family,
        originality_notes=concept.originality_notes,
        status=concept.status,
        production_asset=concept.production_asset,
        created_at=concept.created_at,
    )


def visual_to_item(asset: VisualAsset) -> VisualAssetItem:
    return VisualAssetItem(
        id=asset.id,
        asset_type=asset.asset_type,
        status=asset.status,
        prompt=asset.prompt,
        niche=asset.niche,
        variation_family=asset.variation_family,
        local_path=asset.local_path,
        media_url=local_path_to_media_url(asset.local_path),
        width=asset.width,
        height=asset.height,
        aspect_ratio=asset.aspect_ratio,
        duration_seconds=asset.duration_seconds,
        concept_id=asset.concept_id,
        reference_id=asset.reference_id,
        generation_job_id=asset.generation_job_id,
        production_asset=asset.production_asset,
        reject_reason=asset.reject_reason,
        generated_at=asset.generated_at,
    )


def generation_job_to_item(job: GenerationJob) -> GenerationJobItem:
    return GenerationJobItem(
        id=job.id,
        job_key=job.job_key,
        origin_type=job.origin_type,
        status=job.status,
        image_count=job.image_count,
        video_count=job.video_count,
        style=job.style,
        aspect_ratio=job.aspect_ratio,
        niche=job.niche,
        prompt_summary=job.prompt_summary,
        reference_id=job.reference_id,
        concept_id=job.concept_id,
        source_media_id=job.source_media_id,
        job_json_path=job.job_json_path,
        cursor_prompt_path=job.cursor_prompt_path,
        output_dir=job.output_dir,
        created_at=job.created_at,
    )


def source_media_to_item(source: SourceMedia) -> SourceMediaItem:
    import json

    risk = None
    reuse = None
    if source.risk_explanations_json:
        try:
            payload = json.loads(source.risk_explanations_json)
            risk = RiskScoresItem(**payload)
        except (json.JSONDecodeError, TypeError):
            pass
    if source.reuse_explanations_json:
        try:
            payload = json.loads(source.reuse_explanations_json)
            reuse = ReuseReportItem(**payload)
        except (json.JSONDecodeError, TypeError):
            pass
    return SourceMediaItem(
        id=source.id,
        title=source.title,
        source_mode=source.source_mode,
        media_type=source.media_type,
        reference_id=source.reference_id,
        platform=source.platform,
        external_id=source.external_id,
        url=source.url,
        local_path=source.local_path,
        download_status=source.download_status,
        download_path=source.download_path,
        transcript=source.transcript,
        duration_sec=source.duration_sec,
        rights_confidence=source.rights_confidence,
        monetization_confidence=source.monetization_confidence,
        reuse_confidence=source.reuse_confidence,
        seen_as_reference=source.seen_as_reference,
        actually_used_in_content=source.actually_used_in_content,
        production_asset=source.production_asset,
        created_at=source.created_at,
        risk_scores=risk,
        reuse_report=reuse,
    )


def candidate_to_item(candidate) -> WorkbenchCandidateItem:
    return WorkbenchCandidateItem(
        reference_id=candidate.reference_id,
        title=candidate.title,
        url=candidate.url,
        platform=candidate.platform,
        external_id=candidate.external_id,
        transcript_snippet=candidate.transcript_snippet,
        duration_sec=candidate.duration_sec,
        virality_score=candidate.virality_score,
        reuse_confidence=candidate.reuse_confidence,
        rights_confidence=candidate.rights_confidence,
        monetization_confidence=candidate.monetization_confidence,
        seen_as_reference=candidate.seen_as_reference,
        actually_used_in_content=candidate.actually_used_in_content,
        explanations=candidate.explanations,
    )
