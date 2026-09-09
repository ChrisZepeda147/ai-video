"""Pilot batch creation and pending-task runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from discovery.analytics.refresh import refresh_analytics
from discovery.generation_jobs import import_generation_job, list_pending_generation_jobs
from discovery.pilot.progress import compute_item_stages, refresh_item_progress, summarize_item_status
from discovery.production_projects import build_project_timeline, create_production_project, render_project, transcribe_source
from discovery.acquire import acquire_source_media
from discovery.workbench import find_source_candidates, create_freeform_job, workbench_create_from_candidate
from discovery.store import DiscoveryStore, now_iso


DEFAULT_FIRST_BATCH = (
    {
        "strategy": "podcast_audio",
        "format_profile": "audio_visuals",
        "slot_label": "Short 1",
        "source_mode": "audio",
        "image_count": 6,
        "video_count": 0,
        "query": "unused podcast audio inspirational",
    },
    {
        "strategy": "source_video",
        "format_profile": "source_video_visuals",
        "slot_label": "Short 2",
        "source_mode": "video",
        "image_count": 4,
        "video_count": 2,
        "query": "unused viral source video",
    },
    {
        "strategy": "original_freeform",
        "format_profile": "audio_visuals",
        "slot_label": "Short 3",
        "image_count": 6,
        "video_count": 2,
        "query": "beautiful realistic luxury scenarios nighttime city supercars",
    },
)


@dataclass
class PendingTaskResult:
    action: str
    item_id: int | None = None
    entity_id: int | None = None
    status: str = "done"
    message: str = ""
    requires_human: bool = False


@dataclass
class RunPendingReport:
    batch_id: int | None
    tasks: list[PendingTaskResult] = field(default_factory=list)
    human_required: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def create_pilot_batch(
    store: DiscoveryStore,
    *,
    name: str,
    niche: str,
    account_id: int | None,
    batch_size: int = 3,
    strategies: list[str] | None = None,
    use_first_batch_mix: bool = True,
) -> int:
    slug_base = name.lower().replace(" ", "-")[:40]
    existing = store.get_pilot_batch_by_slug(slug_base)
    slug = slug_base if not existing else f"{slug_base}-{now_iso()[:10]}"

    config = {
        "niche": niche,
        "account_id": account_id,
        "use_first_batch_mix": use_first_batch_mix,
        "strategies": strategies,
    }
    batch_id = store.create_pilot_batch(
        slug=slug,
        name=name,
        niche=niche,
        account_id=account_id,
        batch_size=batch_size,
        config_json=json.dumps(config),
    )

    slots = DEFAULT_FIRST_BATCH[:batch_size] if use_first_batch_mix else []
    if strategies and not use_first_batch_mix:
        for i, strat in enumerate(strategies[:batch_size]):
            slots.append(
                {
                    "strategy": strat,
                    "format_profile": "audio_visuals",
                    "slot_label": f"Short {i + 1}",
                    "source_mode": "audio" if "audio" in strat else "video",
                    "image_count": 6,
                    "video_count": 0,
                    "query": f"unused {niche} {strat.replace('_', ' ')}",
                }
            )

    for order, slot in enumerate(slots):
        item_id = store.create_pilot_batch_item(
            batch_id=batch_id,
            sort_order=order,
            slot_label=slot.get("slot_label") or f"Short {order + 1}",
            strategy=slot["strategy"],
            format_profile=slot.get("format_profile", "audio_visuals"),
        )
        _bootstrap_pilot_item(store, item_id, niche=niche, slot=slot)

    store.update_pilot_batch_status(batch_id, "active", started_at=now_iso())
    return batch_id


def _bootstrap_pilot_item(store: DiscoveryStore, item_id: int, *, niche: str, slot: dict[str, Any]) -> None:
    strategy = slot["strategy"]
    try:
        if strategy == "original_freeform":
            job = create_freeform_job(
                store,
                slot.get("query") or f"original {niche} luxury visuals",
                image_count=slot.get("image_count", 6),
                video_count=slot.get("video_count", 0),
                style=niche,
            )
            store.update_pilot_batch_item(
                item_id,
                generation_job_id=job.job.id,
                notes="Freeform generation job created",
            )
        else:
            query = f"{slot.get('query', 'unused')} {niche}"
            candidates = find_source_candidates(store, query, limit=5, niche=niche)
            if not candidates:
                store.update_pilot_batch_item(
                    item_id,
                    error_stage="reference",
                    error_message=f"No candidates for query: {query}",
                )
                return
            candidate = candidates[0]
            result = workbench_create_from_candidate(
                store,
                candidate,
                source_mode=slot.get("source_mode", "audio"),
                image_count=slot.get("image_count", 6),
                video_count=slot.get("video_count", 0),
            )
            store.update_pilot_batch_item(
                item_id,
                reference_id=candidate.reference_id,
                source_media_id=result["source"].source.id,
                generation_job_id=result["job"].job.id if result.get("job") else None,
                notes=f"Source from: {candidate.title[:80]}",
            )
    except Exception as exc:
        store.update_pilot_batch_item(item_id, error_stage="bootstrap", error_message=str(exc))

    refresh_item_progress(store, item_id)


def _maybe_create_project(store: DiscoveryStore, item, *, niche: str | None = None) -> int | None:
    if item.production_project_id:
        return item.production_project_id
    if not item.source_media_id and item.strategy != "original_freeform":
        return None
    stages = compute_item_stages(store, item)
    if stages.get("visual_approval", {}).get("status") != "complete":
        return None
    source = store.get_source_media(item.source_media_id) if item.source_media_id else None
    title = item.slot_label or f"Pilot Short {item.id}"
    if source:
        title = source.title[:80]
    batch = store.get_pilot_batch(item.batch_id)
    result = create_production_project(
        store,
        title=title,
        niche=niche or (batch.niche if batch else None),
        source_media_id=item.source_media_id,
        reference_id=item.reference_id,
        format_profile=item.format_profile or "audio_visuals",
    )
    store.update_pilot_batch_item(item.id, production_project_id=result.project_id)
    return result.project_id


def run_pending_pilot_tasks(
    store: DiscoveryStore,
    *,
    batch_id: int | None = None,
    limit: int = 20,
    live_publish: bool = False,
) -> RunPendingReport:
    """Run safe automated steps for pilot items. Never live-publishes unless live_publish=True."""
    report = RunPendingReport(batch_id=batch_id)
    batches = [store.get_pilot_batch(batch_id)] if batch_id else store.list_pilot_batches(status="active", limit=5)
    batches = [b for b in batches if b]

    for batch in batches:
        items = store.list_pilot_batch_items(batch.id)
        for item in items[:limit]:
            refresh_item_progress(store, item.id)
            item = store.get_pilot_batch_item(item.id)
            if not item:
                continue

            # Acquire source
            if item.source_media_id:
                source = store.get_source_media(item.source_media_id)
                if source and source.download_status not in ("acquired",) and source.local_path is None:
                    try:
                        acquire_source_media(store, item.source_media_id)
                        report.tasks.append(
                            PendingTaskResult("acquire_source", item.id, item.source_media_id, message="Downloaded")
                        )
                    except Exception as exc:
                        report.errors.append(f"Item #{item.id} acquire: {exc}")
                        store.update_pilot_batch_item(item.id, error_stage="source_acquired", error_message=str(exc))

            # Transcribe
            if item.source_media_id:
                source = store.get_source_media(item.source_media_id)
                transcript = (source.transcript or "") if source else ""
                if source and source.download_status == "acquired" and (
                    not transcript or transcript.startswith("[transcript pending")
                ):
                    try:
                        transcribe_source(store, item.source_media_id)
                        report.tasks.append(
                            PendingTaskResult("transcribe", item.id, item.source_media_id, message="Transcribed")
                        )
                    except Exception as exc:
                        report.errors.append(f"Item #{item.id} transcribe: {exc}")

            # Import generation jobs linked to batch
            if item.generation_job_id:
                job = store.get_generation_job(item.generation_job_id)
                if job and job.status == "pending":
                    report.human_required.append(
                        f"Item #{item.id}: Cursor generation pending for job {job.job_key} — "
                        f"see data/generation_jobs/{job.job_key}/"
                    )

            # Auto-import any pending jobs in batch context
            for job in list_pending_generation_jobs(store, limit=5):
                if item.generation_job_id and job.id != item.generation_job_id:
                    continue
                try:
                    output_dir = job.output_dir
                    if output_dir and __import__("pathlib").Path(output_dir).is_dir():
                        result = import_generation_job(store, job.id)
                        if result.get("imported", 0) > 0:
                            report.tasks.append(
                                PendingTaskResult(
                                    "import_generation",
                                    item.id,
                                    job.id,
                                    message=f"Imported {result['imported']} assets",
                                )
                            )
                except Exception:
                    pass

            refresh_item_progress(store, item.id)
            item = store.get_pilot_batch_item(item.id)

            # Visual approval gate
            stages = compute_item_stages(store, item)
            if stages.get("visual_generation", {}).get("status") == "waiting_cursor":
                report.human_required.append(f"Item #{item.id}: Waiting for Cursor visual generation")
            if stages.get("visual_approval", {}).get("status") == "waiting_human":
                report.human_required.append(f"Item #{item.id}: Approve visuals on /review")

            # Create project when visuals ready
            try:
                _maybe_create_project(store, item, niche=batch.niche)
            except Exception as exc:
                report.errors.append(f"Item #{item.id} create project: {exc}")

            item = store.get_pilot_batch_item(item.id)
            if item and item.production_project_id:
                project = store.get_production_project(item.production_project_id)
                if project and project.status == "draft":
                    try:
                        build_project_timeline(store, item.production_project_id)
                        report.tasks.append(
                            PendingTaskResult("build_timeline", item.id, project.id, message="Timeline built")
                        )
                    except Exception as exc:
                        report.errors.append(f"Item #{item.id} timeline: {exc}")

                project = store.get_production_project(item.production_project_id)
                if project and project.status == "ready":
                    try:
                        render_project(store, item.production_project_id)
                        report.tasks.append(
                            PendingTaskResult("render", item.id, project.id, message="Rendered")
                        )
                    except Exception as exc:
                        report.errors.append(f"Item #{item.id} render: {exc}")
                        store.update_pilot_batch_item(
                            item.id, error_stage="render", error_message=str(exc)
                        )

                project = store.get_production_project(item.production_project_id)
                if project and project.status == "review":
                    report.human_required.append(
                        f"Item #{item.id}: Project #{project.id} ready for final approval on /review"
                    )

            if item and item.publishing_job_id and live_publish:
                report.human_required.append(
                    "Live publish requested — use publish dialog with explicit confirmation"
                )

            # Analytics refresh for published
            if item and item.publishing_job_id:
                job = store.get_publishing_job(item.publishing_job_id)
                if job and job.status in ("published", "processing"):
                    refresh_analytics(store, job_id=job.id, force=False)

            refresh_item_progress(store, item.id)

    return report


def get_pilot_results(store: DiscoveryStore, batch_id: int) -> list[dict[str, Any]]:
    """Aggregate pilot comparison data — advisory, not causal."""
    items = store.list_pilot_batch_items(batch_id)
    results: list[dict[str, Any]] = []
    for item in items:
        refresh_item_progress(store, item.id)
        item = store.get_pilot_batch_item(item.id)
        if not item:
            continue
        stages = json.loads(item.stages_json) if item.stages_json else {}
        row: dict[str, Any] = {
            "item_id": item.id,
            "slot_label": item.slot_label,
            "strategy": item.strategy,
            "format_profile": item.format_profile,
            "status": item.status,
            "stages": stages,
            "error_stage": item.error_stage,
            "error_message": item.error_message,
        }
        features: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        if item.production_project_id:
            project = store.get_production_project(item.production_project_id)
            if project:
                row["title"] = project.title
                row["duration_sec"] = project.duration_sec
                row["hook_text"] = project.hook_text
        if item.publishing_job_id:
            snap = store.get_latest_analytics_snapshot(item.publishing_job_id)
            feat_row = store.get_analytics_post_features(item.publishing_job_id)
            if feat_row:
                features = json.loads(feat_row.features_json)
            if snap:
                metrics = {
                    "views": snap.views,
                    "likes": snap.likes,
                    "comments": snap.comments,
                    "performance_score": snap.performance_score,
                    "performance_tier": snap.performance_tier,
                }
        row["features"] = features
        row["metrics"] = metrics
        row["disclaimer"] = "Small sample — correlations are not causation."
        results.append(row)
    return results
