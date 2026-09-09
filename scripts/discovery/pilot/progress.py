"""Compute end-to-end pilot progress for each Short."""

from __future__ import annotations

import json
from typing import Any

STAGE_KEYS = (
    "reference",
    "source_acquired",
    "transcript",
    "visual_generation",
    "visual_approval",
    "timeline",
    "render",
    "final_approval",
    "publishing",
    "analytics",
)

StageStatus = str  # pending | complete | waiting_cursor | waiting_human | failed | skipped | in_progress


def _stage(status: StageStatus, *, message: str = "", entity_id: int | None = None) -> dict[str, Any]:
    return {"status": status, "message": message, "entity_id": entity_id}


def compute_item_stages(store, item) -> dict[str, Any]:
    """Derive stage statuses from linked pipeline entities."""
    stages: dict[str, Any] = {}

    strategy = item.strategy or ""
    is_freeform = strategy == "original_freeform"

    # Reference
    if is_freeform:
        stages["reference"] = _stage("skipped", message="Original/freeform — no reference required")
    elif item.reference_id:
        ref = store.get_reference_by_id(item.reference_id)
        stages["reference"] = _stage(
            "complete" if ref else "failed",
            message=ref.title if ref else "Reference missing",
            entity_id=item.reference_id,
        )
    else:
        stages["reference"] = _stage("pending", message="Find or assign a reference")

    # Source acquired
    if item.source_media_id:
        source = store.get_source_media(item.source_media_id)
        if not source:
            stages["source_acquired"] = _stage("failed", message="Source media record missing")
        elif source.download_status == "acquired" or source.local_path:
            stages["source_acquired"] = _stage("complete", message="Source downloaded", entity_id=item.source_media_id)
        elif source.download_status == "failed":
            stages["source_acquired"] = _stage(
                "failed",
                message="Download failed — retry acquire",
                entity_id=item.source_media_id,
            )
        else:
            stages["source_acquired"] = _stage(
                "in_progress",
                message="Waiting for download",
                entity_id=item.source_media_id,
            )
    elif is_freeform:
        stages["source_acquired"] = _stage("skipped", message="No external source")
    else:
        stages["source_acquired"] = _stage("pending", message="Acquire source media")

    # Transcript
    if item.source_media_id:
        source = store.get_source_media(item.source_media_id)
        transcript = (source.transcript or "") if source else ""
        if transcript and not transcript.startswith("[transcript pending"):
            stages["transcript"] = _stage("complete", message="Transcript ready", entity_id=item.source_media_id)
        elif source and source.download_status == "acquired":
            stages["transcript"] = _stage("in_progress", message="Run transcription", entity_id=item.source_media_id)
        else:
            stages["transcript"] = _stage("pending", message="Needs source first")
    else:
        stages["transcript"] = _stage("skipped", message="No source to transcribe")

    # Visual generation
    if item.generation_job_id:
        job = store.get_generation_job(item.generation_job_id)
        if not job:
            stages["visual_generation"] = _stage("failed", message="Generation job missing")
        elif job.status == "pending":
            stages["visual_generation"] = _stage(
                "waiting_cursor",
                message="Waiting for Cursor — generate assets then import",
                entity_id=item.generation_job_id,
            )
        elif job.status in ("imported", "completed"):
            stages["visual_generation"] = _stage("complete", message="Assets imported", entity_id=item.generation_job_id)
        else:
            stages["visual_generation"] = _stage("in_progress", message=f"Job status: {job.status}")
    else:
        stages["visual_generation"] = _stage("pending", message="Create generation job")

    # Visual approval
    gen_job = store.get_generation_job(item.generation_job_id) if item.generation_job_id else None
    if item.generation_job_id:
        visuals = store.list_visual_assets_by_generation_job(item.generation_job_id)
        approved_count = sum(1 for v in visuals if v.status == "approved")
        review_count = sum(1 for v in visuals if v.status == "review")
        if approved_count > 0:
            stages["visual_approval"] = _stage(
                "complete",
                message=f"{approved_count} approved visual(s)",
                entity_id=item.generation_job_id,
            )
        elif review_count > 0:
            stages["visual_approval"] = _stage(
                "waiting_human",
                message=f"{review_count} visual(s) awaiting review on /review",
                entity_id=item.generation_job_id,
            )
        elif gen_job and gen_job.status in ("imported", "completed"):
            stages["visual_approval"] = _stage("waiting_human", message="Import done — approve visuals")
        else:
            stages["visual_approval"] = _stage("pending", message="Needs generated visuals")
    else:
        stages["visual_approval"] = _stage("pending", message="Needs generation job")

    # Production project stages
    if item.production_project_id:
        project = store.get_production_project(item.production_project_id)
        if not project:
            stages["timeline"] = _stage("failed", message="Project missing")
            stages["render"] = _stage("failed", message="Project missing")
            stages["final_approval"] = _stage("failed", message="Project missing")
        else:
            if project.timeline_json:
                stages["timeline"] = _stage("complete", message="Timeline built", entity_id=project.id)
            elif project.status == "draft":
                stages["timeline"] = _stage("pending", message="Build timeline on /create")
            else:
                stages["timeline"] = _stage("in_progress", message=f"Status: {project.status}")

            if project.output_path and project.status in ("review", "approved", "rendered"):
                stages["render"] = _stage("complete", message="Rendered", entity_id=project.id)
            elif project.status == "rendering":
                stages["render"] = _stage("in_progress", message="Rendering…")
            elif project.status == "failed":
                stages["render"] = _stage(
                    "failed",
                    message=project.error_message or "Render failed",
                    entity_id=project.id,
                )
            elif project.status in ("ready", "draft"):
                stages["render"] = _stage("pending", message="Render when timeline ready")
            else:
                stages["render"] = _stage("pending", message=f"Status: {project.status}")

            if project.status == "approved":
                stages["final_approval"] = _stage("complete", message="Approved for publish", entity_id=project.id)
            elif project.status == "review":
                stages["final_approval"] = _stage("waiting_human", message="Awaiting approval on /review")
            elif project.status == "rejected":
                stages["final_approval"] = _stage("failed", message="Rejected")
            else:
                stages["final_approval"] = _stage("pending", message="Needs render + review")
    else:
        stages["timeline"] = _stage("pending", message="Create production project")
        stages["render"] = _stage("pending", message="Create production project")
        stages["final_approval"] = _stage("pending", message="Create production project")

    # Publishing
    if item.publishing_job_id:
        job = store.get_publishing_job(item.publishing_job_id)
        if job and job.status in ("published", "processing"):
            stages["publishing"] = _stage(
                "complete",
                message=job.platform_url or job.platform_post_id or "Published",
                entity_id=item.publishing_job_id,
            )
        elif job and job.status == "failed":
            stages["publishing"] = _stage(
                "failed",
                message=job.error_message or "Publish failed",
                entity_id=item.publishing_job_id,
            )
        elif job:
            stages["publishing"] = _stage(
                "waiting_human",
                message=f"Job {job.status} — publish from /review or /videos",
                entity_id=item.publishing_job_id,
            )
        else:
            stages["publishing"] = _stage("failed", message="Publishing job missing")
    else:
        proj = store.get_production_project(item.production_project_id) if item.production_project_id else None
        if proj and proj.status == "approved":
            stages["publishing"] = _stage("waiting_human", message="Ready — create publish job")
        else:
            stages["publishing"] = _stage("pending", message="Awaiting approved Short")

    # Analytics
    if item.publishing_job_id:
        snap = store.get_latest_analytics_snapshot(item.publishing_job_id)
        if snap:
            stages["analytics"] = _stage(
                "complete",
                message=f"Score {snap.performance_score} / {snap.performance_tier}",
                entity_id=item.publishing_job_id,
            )
        else:
            job = store.get_publishing_job(item.publishing_job_id)
            if job and job.status in ("published", "processing"):
                stages["analytics"] = _stage("in_progress", message="Run analytics refresh")
            else:
                stages["analytics"] = _stage("pending", message="After publish")
    else:
        stages["analytics"] = _stage("pending", message="After publish")

    return stages


def summarize_item_status(stages: dict[str, Any]) -> str:
    if any(stages.get(k, {}).get("status") == "failed" for k in STAGE_KEYS):
        return "failed"
    if stages.get("analytics", {}).get("status") == "complete":
        return "complete"
    if stages.get("publishing", {}).get("status") == "complete":
        return "published"
    if stages.get("final_approval", {}).get("status") == "complete":
        return "approved"
    if stages.get("render", {}).get("status") == "complete":
        return "rendered"
    if stages.get("visual_approval", {}).get("status") == "complete":
        return "visuals_ready"
    if stages.get("visual_generation", {}).get("status") == "complete":
        return "visuals_imported"
    if stages.get("source_acquired", {}).get("status") == "complete":
        return "source_ready"
    return "in_progress"


def refresh_item_progress(store, item_id: int) -> dict[str, Any]:
    item = store.get_pilot_batch_item(item_id)
    if not item:
        raise ValueError(f"Pilot item {item_id} not found")
    stages = compute_item_stages(store, item)
    status = summarize_item_status(stages)
    store.update_pilot_batch_item(
        item_id,
        stages_json=json.dumps(stages),
        status=status,
    )
    return stages
