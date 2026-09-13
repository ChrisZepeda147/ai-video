"""FastAPI API for the discovery catalog (read + thin write wrappers)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.deps import get_store  # noqa: F401 — scripts path + load_env before discovery imports
from api.internal_auth import require_internal_key

from api.converters import (
    analysis_to_item,
    candidate_to_item,
    concept_to_item,
    generation_job_to_item,
    source_media_to_item,
    top_to_reference_item,
    visual_to_item,
)
from api.schemas import (
    AnalysisResponse,
    AnalyzeRequest,
    ConceptIdsRequest,
    ConceptStatusResponse,
    ConceptsResponse,
    DiscoverRequest,
    DiscoverResponse,
    DiscoveryStats,
    GenerateConceptsRequest,
    GenerateConceptsResponse,
    NicheCoverageItem,
    ReferenceItem,
    ReferencesResponse,
    ScanRequest,
    ScanResponse,
    SourceMediaResponse,
    SourceSegmentItem,
    SourceSegmentRequest,
    TranscribeRequest,
    VisualIdsRequest,
    VisualStatusResponse,
    VisualsReviewResponse,
    WorkbenchCreateFromCandidateRequest,
    WorkbenchCreateRequest,
    WorkbenchFindRequest,
    WorkbenchFindResponse,
    PublishingAccountItem,
    PublishingAccountsResponse,
    ConnectAccountRequest,
    ConnectAccountResponse,
    CompleteConnectRequest,
    CreatePublishingJobRequest,
    PublishingJobItem,
    PublishingJobsResponse,
    AnalyticsOverview,
    AnalyticsPostsResponse,
    AnalyticsPostItem,
    AnalyticsPatternsResponse,
    AnalyticsPatternItem,
    AnalyticsRefreshRequest,
    AnalyticsRefreshResponse,
    PerformanceProfileResponse,
    ProjectAnalyticsResponse,
    PreflightResponse,
    PreflightCheckItem,
    CreatePilotBatchRequest,
    PilotBatchResponse,
    PilotBatchItemResponse,
    PilotStageItem,
    PilotBatchesResponse,
    RunPilotPendingRequest,
    RunPilotPendingResponse,
    TestPublishRequest,
    CreateGenerationJobRequest,
    CreateSourceMediaRequest,
    GenerationJobItem,
    GenerationJobsResponse,
    ImportJobResponse,
    ReuseReportItem,
    RiskScoresItem,
    reference_item_from_store,
)
from discovery.analyze import analyze_reference
from discovery.concepts import generate_concepts_for_reference
from discovery.config import HIGH_VIRALITY_SCORE, default_niches_path, project_root
from discovery.acquire import acquire_source_media, clip_source_segment
from discovery.generation_jobs import create_generation_job, import_generation_job
from discovery.production_projects import (
    approve_project,
    build_project_timeline,
    create_production_project,
    reject_project,
    render_project,
    send_project_to_review,
)
from discovery.command_jobs import get_command_job, list_command_jobs, submit_command
from discovery.cursor_bridge import agent_available
from discovery.motivation_build import build_defaults, read_job, start_motivation_build
from discovery.combination_render import render_combination
from discovery.combinations import (
    catalog_payload,
    combination_status,
    import_usage_from_videos,
    prune_stale_combination_catalog,
    sync_visual_packs,
)
from discovery.production_library import (
    check_reuse,
    get_video,
    import_uploaded_video,
    list_videos,
    prune_missing_components,
    update_video_posting_status,
)
from discovery.speaker_identity import KNOWN_SPEAKERS, update_video_speaker
from discovery.shared_library import maybe_auto_pull_import, pull_and_import, sync_status
from discovery.site_videos import import_videos_to_site
from discovery.video_library import (
    build_video_library,
    library_summary,
    delete_video_library_item,
    prune_missing_legacy_catalog,
    update_video_library_item,
)
from discovery.publishing.accounts import (
    complete_account_connect,
    disconnect_account,
    import_mock_account,
    start_account_connect,
    verify_publishing_account,
)
from discovery.publishing.jobs import (
    cancel_publishing_job,
    create_publishing_jobs,
    publish_job,
    retry_publishing_job,
)
from discovery.source_media import add_source_segment, create_source_from_reference, create_source_media, transcribe_source_media
from discovery.analytics.discovery_feedback import compute_internal_fit
from discovery.analytics.patterns import (
    aggregate_accounts,
    aggregate_formats,
    aggregate_hooks,
    aggregate_sources,
    aggregate_topics,
    aggregate_visuals,
)
from discovery.analytics.profiles import build_performance_profile
from discovery.analytics.refresh import refresh_analytics
from discovery.analytics.scoring import performance_signals
from discovery.pilot.preflight import run_preflight
from discovery.pilot.batches import create_pilot_batch, get_pilot_results, run_pending_pilot_tasks
from discovery.pilot.progress import refresh_item_progress
from discovery.publishing.jobs import create_test_publish_job, publish_test_upload
from discovery.workbench import create_freeform_job, find_source_candidates, workbench_create_from_candidate
from discovery.engine import ingest_youtube_search, run_multi_niche_discovery
from discovery.niches import enabled_niches, load_niches_config
from discovery.providers.base import ProviderError
from discovery.providers.factory import build_analysis_provider
from discovery.store import DiscoveryStore

app = FastAPI(
    title="Ai-Video Discovery API",
    description="Read/write API over the Python discovery SQLite catalog.",
    version="0.2.0",
)

_cors_origins = os.environ.get(
    "DISCOVERY_API_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

_root = project_root()
app.mount("/media", StaticFiles(directory=str(_root)), name="media")


@app.on_event("startup")
def _configure_stdio_utf8() -> None:
    import sys

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


@app.on_event("startup")
def _start_shared_library_auto_sync() -> None:
    import logging
    import threading
    import time

    from discovery.config import default_db_path
    from discovery.shared_library import auto_sync_enabled, auto_sync_interval_minutes, maybe_auto_pull_import

    if not auto_sync_enabled():
        return

    def _loop() -> None:
        interval_sec = auto_sync_interval_minutes() * 60
        time.sleep(min(15, interval_sec))
        while True:
            try:
                db = default_db_path()
                if Path(db).is_file():
                    store = DiscoveryStore(db)
                    try:
                        result = maybe_auto_pull_import(store)
                        if result and int(result.get("import", {}).get("imported", 0) or 0) > 0:
                            logging.getLogger("uvicorn.error").info(
                                "Stephen auto-sync: imported %s package(s)",
                                result["import"]["imported"],
                            )
                    finally:
                        store.close()
            except Exception as exc:
                logging.getLogger("uvicorn.error").warning("Stephen auto-sync failed: %s", exc)
            time.sleep(interval_sec)

    threading.Thread(target=_loop, name="shared-library-auto-sync", daemon=True).start()


@app.on_event("startup")
def _start_brother_code_auto_pull() -> None:
    import logging
    import threading
    import time

    from discovery.brother_code_sync import auto_pull_enabled, auto_pull_interval_minutes, maybe_auto_brother_code_pull
    from discovery.config import default_db_path

    if not auto_pull_enabled():
        return

    def _loop() -> None:
        interval_sec = auto_pull_interval_minutes() * 60
        time.sleep(min(30, interval_sec))
        while True:
            try:
                db = default_db_path()
                if Path(db).is_file():
                    store = DiscoveryStore(db)
                    try:
                        result = maybe_auto_brother_code_pull(store)
                        if result and result.get("pull", {}).get("pulled"):
                            logging.getLogger("uvicorn.error").info(
                                "Brother code auto-pull: %s",
                                result["pull"].get("message") or "updated",
                            )
                        elif result and result.get("pull", {}).get("skipped"):
                            logging.getLogger("uvicorn.error").info(
                                "Brother code auto-pull skipped: %s",
                                result["pull"].get("reason") or "dirty tree",
                            )
                    finally:
                        store.close()
            except Exception as exc:
                logging.getLogger("uvicorn.error").warning("Brother code auto-pull failed: %s", exc)
            time.sleep(interval_sec)

    threading.Thread(target=_loop, name="brother-code-auto-pull", daemon=True).start()


@app.on_event("startup")
def _start_analytics_auto_refresh() -> None:
    import logging
    import os
    import threading
    import time

    from discovery.analytics.account_summary import refresh_owner_analytics
    from discovery.config import default_db_path, publishing_owner

    if os.environ.get("ANALYTICS_AUTO_REFRESH", "1").strip().lower() in ("0", "false", "no"):
        return

    def _interval_minutes() -> int:
        try:
            return max(30, int(os.environ.get("ANALYTICS_AUTO_REFRESH_MINUTES", "360")))
        except ValueError:
            return 360

    def _loop() -> None:
        interval_sec = _interval_minutes() * 60
        time.sleep(min(60, interval_sec))
        while True:
            try:
                db = default_db_path()
                if Path(db).is_file():
                    store = DiscoveryStore(db)
                    try:
                        result = refresh_owner_analytics(
                            store,
                            owner=publishing_owner(),
                            limit=50,
                            force=False,
                        )
                        if result.get("refreshed"):
                            logging.getLogger("uvicorn.error").info(
                                "Analytics auto-refresh: %s posts for %s",
                                result["refreshed"],
                                result.get("owner") or "all",
                            )
                    finally:
                        store.close()
            except Exception as exc:
                logging.getLogger("uvicorn.error").warning("Analytics auto-refresh failed: %s", exc)
            time.sleep(interval_sec)

    threading.Thread(target=_loop, name="analytics-auto-refresh", daemon=True).start()


def _provider():
    try:
        return build_analysis_provider(provider="auto")
    except ProviderError:
        return build_analysis_provider(provider="prompt_export", prompt_export=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/discovery/stats", response_model=DiscoveryStats)
def discovery_stats(
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> DiscoveryStats:
    catalog = store.catalog_stats()
    visuals = store.visual_library_stats()
    concepts_ready = store.count_concepts(statuses=("generated", "shortlisted", "approved"))
    enabled = enabled_niches(default_niches_path())
    coverage = {item.niche: item.reference_count for item in catalog.niche_coverage}
    niche_coverage = [
        NicheCoverageItem(
            niche=name,
            reference_count=coverage.get(name, 0),
            enabled=cfg.enabled,
        )
        for name, cfg in sorted(enabled.items())
    ]
    return DiscoveryStats(
        total_references=catalog.total_references,
        references_added_today=catalog.references_added_today,
        high_virality_references=catalog.high_virality_references,
        searches_today=catalog.searches_today,
        detail_requests_today=catalog.detail_requests_today,
        discovery_runs=catalog.discovery_runs,
        production_assets=catalog.production_assets,
        concepts_ready=concepts_ready,
        visuals_waiting_review=visuals.waiting_review,
        niche_coverage=niche_coverage,
    )


@app.get("/api/discovery/references", response_model=ReferencesResponse)
def discovery_references(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(25, ge=1, le=200),
    search: str | None = None,
    status: str | None = Query(
        None,
        description="Filter: active, exhausted, analyzed, unanalyzed",
    ),
) -> ReferencesResponse:
    rows = store.list_dashboard_references(
        niche=niche,
        min_score=min_score,
        limit=limit,
        search=search,
        status=status,
    )
    enriched: list[dict] = []
    for row in rows:
        ref = row["reference"]
        fit = compute_internal_fit(store, reference_id=int(ref.id), niche=niche)
        row = dict(row)
        row["internal_fit_score"] = fit.get("internal_fit_score")
        row["internal_fit_note"] = fit.get("internal_fit_note")
        enriched.append(row)
    items = [reference_item_from_store(row) for row in enriched]
    return ReferencesResponse(items=items, count=len(items))


@app.get("/api/discovery/top", response_model=ReferencesResponse)
def discovery_top(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    min_score: float = Query(HIGH_VIRALITY_SCORE, ge=0.0, le=100.0),
    limit: int = Query(25, ge=1, le=200),
) -> ReferencesResponse:
    tops = store.list_top_references(niche=niche, min_score=min_score, limit=limit)
    items = [top_to_reference_item(store, top) for top in tops]
    return ReferencesResponse(items=items, count=len(items))


@app.get("/api/discovery/niches")
def discovery_niches(
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> dict[str, list[NicheCoverageItem]]:
    catalog = store.catalog_stats()
    coverage = {item.niche: item.reference_count for item in catalog.niche_coverage}
    config = load_niches_config(default_niches_path())
    items = [
        NicheCoverageItem(
            niche=name,
            reference_count=coverage.get(name, 0),
            enabled=cfg.enabled,
        )
        for name, cfg in sorted(config.items())
    ]
    return {"items": items}


@app.post("/api/discovery/scan", response_model=ScanResponse)
def discovery_scan(
    body: ScanRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> ScanResponse:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        stats = ingest_youtube_search(
            store,
            query=query,
            limit=body.limit,
            shorts_only=True,
            niche=body.niche,
            force_search=body.force,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ScanResponse(
        query=query,
        ids_found=stats.ids_found,
        ids_new=stats.ids_new,
        ids_updated=stats.ids_updated,
        ids_existing=stats.ids_existing,
        ids_skipped_refresh=stats.ids_skipped_refresh,
        detail_requests=stats.detail_requests,
        searches_executed=stats.searches_executed,
        searches_skipped=stats.searches_skipped,
        skipped_cooldown=bool(stats.searches_skipped),
    )


@app.post("/api/discovery/discover", response_model=DiscoverResponse)
def discovery_discover_all(
    body: DiscoverRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> DiscoverResponse:
    try:
        result = run_multi_niche_discovery(
            store,
            max_searches=body.max_searches,
            force_search=body.force,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DiscoverResponse(
        searches_executed=result.searches_executed,
        searches_skipped_cooldown=result.searches_skipped_cooldown,
        searches_skipped_limit=result.searches_skipped_limit,
        searches_skipped_niche_cap=result.searches_skipped_niche_cap,
        ids_new=result.ids_new,
        ids_updated=result.ids_updated,
        ids_existing=result.ids_existing,
        detail_requests=result.detail_requests,
        skipped_terms=result.skipped_terms,
    )


@app.get("/api/discovery/references/{reference_id}/analysis", response_model=AnalysisResponse)
def get_reference_analysis(
    reference_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    latest: bool = True,
) -> AnalysisResponse:
    if store.get_reference_by_id(reference_id) is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    if latest:
        analysis = store.get_latest_analysis(reference_id)
        if analysis is None:
            return AnalysisResponse(item=None, items=[])
        item = analysis_to_item(analysis)
        return AnalysisResponse(item=item, items=[item])
    analyses = store.list_analyses(reference_id)
    items = [analysis_to_item(a) for a in analyses]
    return AnalysisResponse(item=items[0] if items else None, items=items)


@app.post("/api/discovery/references/{reference_id}/analyze", response_model=AnalysisResponse)
def analyze_reference_endpoint(
    reference_id: int,
    body: AnalyzeRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> AnalysisResponse:
    if store.get_reference_by_id(reference_id) is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    if not body.reanalyze:
        existing = store.get_latest_analysis(reference_id)
        if existing is not None:
            item = analysis_to_item(existing, cached=True)
            return AnalysisResponse(item=item, items=[item])
    try:
        provider = _provider()
        analysis = analyze_reference(store, reference_id, provider)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    item = analysis_to_item(analysis)
    return AnalysisResponse(item=item, items=[item])


@app.post(
    "/api/discovery/references/{reference_id}/concepts",
    response_model=GenerateConceptsResponse,
)
def generate_concepts_endpoint(
    reference_id: int,
    body: GenerateConceptsRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> GenerateConceptsResponse:
    if store.get_reference_by_id(reference_id) is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    try:
        provider = _provider()
        result = generate_concepts_for_reference(
            store,
            reference_id=reference_id,
            count=body.count,
            provider=provider,
            niche=body.niche,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    concepts = [concept_to_item(store, c) for c in result.concepts]
    return GenerateConceptsResponse(
        reference_id=result.reference_id,
        requested=result.requested,
        stored=result.stored,
        rejected_similar=result.rejected_similar,
        skipped_exhaustion=result.skipped_exhaustion,
        concepts=concepts,
    )


@app.get("/api/discovery/concepts", response_model=ConceptsResponse)
def list_concepts_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    reference_id: int | None = None,
    niche: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> ConceptsResponse:
    concepts = store.list_concepts(
        reference_id=reference_id,
        niche=niche,
        status=status,
        limit=limit,
    )
    items = [concept_to_item(store, c) for c in concepts]
    return ConceptsResponse(items=items, count=len(items))


@app.post("/api/discovery/concepts/shortlist", response_model=ConceptStatusResponse)
def shortlist_concepts_endpoint(
    body: ConceptIdsRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> ConceptStatusResponse:
    updated = store.shortlist_concepts(body.concept_ids)
    return ConceptStatusResponse(updated=updated, count=len(updated))


@app.post("/api/discovery/concepts/approve", response_model=ConceptStatusResponse)
def approve_concepts_endpoint(
    body: ConceptIdsRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> ConceptStatusResponse:
    updated = store.approve_concepts(body.concept_ids)
    return ConceptStatusResponse(updated=updated, count=len(updated))


@app.post("/api/discovery/concepts/reject", response_model=ConceptStatusResponse)
def reject_concepts_endpoint(
    body: ConceptIdsRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> ConceptStatusResponse:
    updated = store.reject_concepts(body.concept_ids)
    return ConceptStatusResponse(updated=updated, count=len(updated))


@app.post("/api/source-media", response_model=SourceMediaResponse)
def create_source_media_endpoint(
    body: CreateSourceMediaRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> SourceMediaResponse:
    try:
        if body.reference_id and not body.title:
            result = create_source_from_reference(store, body.reference_id, body.source_mode)
        else:
            result = create_source_media(
                store,
                title=body.title or "Untitled source",
                source_mode=body.source_mode,
                media_type=body.media_type,
                reference_id=body.reference_id,
                platform=body.platform,
                external_id=body.external_id,
                url=body.url,
                local_path=body.local_path,
                transcript=body.transcript,
                duration_sec=body.duration_sec,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SourceMediaResponse(
        item=source_media_to_item(result.source),
        reuse_report=ReuseReportItem(**result.reuse_report),
        risk_scores=RiskScoresItem(**result.risk_scores),
    )


@app.post("/api/source-media/{source_media_id}/segment", response_model=SourceSegmentItem)
def add_source_segment_endpoint(
    source_media_id: int,
    body: SourceSegmentRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> SourceSegmentItem:
    try:
        segment = add_source_segment(
            store,
            source_media_id,
            start_sec=body.start_sec,
            end_sec=body.end_sec,
            transcript=body.transcript,
            local_path=body.local_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SourceSegmentItem(
        id=segment.id,
        source_media_id=segment.source_media_id,
        start_sec=segment.start_sec,
        end_sec=segment.end_sec,
        transcript=segment.transcript,
        local_path=segment.local_path,
    )


@app.post("/api/source-media/{source_media_id}/transcribe", response_model=SourceMediaResponse)
def transcribe_source_endpoint(
    source_media_id: int,
    body: TranscribeRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> SourceMediaResponse:
    try:
        source = transcribe_source_media(store, source_media_id, transcript=body.transcript)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item = source_media_to_item(source)
    return SourceMediaResponse(
        item=item,
        reuse_report=item.reuse_report or ReuseReportItem(),
        risk_scores=item.risk_scores or RiskScoresItem(),
    )


@app.post("/api/generation/jobs", response_model=GenerationJobItem)
def create_generation_job_endpoint(
    body: CreateGenerationJobRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> GenerationJobItem:
    try:
        result = create_generation_job(
            store,
            origin_type=body.origin_type,
            prompt_summary=body.prompt_summary,
            image_count=body.image_count,
            video_count=body.video_count,
            style=body.style,
            aspect_ratio=body.aspect_ratio,
            niche=body.niche,
            reference_id=body.reference_id,
            concept_id=body.concept_id,
            source_media_id=body.source_media_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return generation_job_to_item(result.job)


@app.get("/api/generation/jobs", response_model=GenerationJobsResponse)
def list_generation_jobs_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> GenerationJobsResponse:
    jobs = store.list_generation_jobs(status=status, limit=limit)
    items = [generation_job_to_item(j) for j in jobs]
    return GenerationJobsResponse(items=items, count=len(items))


@app.get("/api/generation/jobs/{job_id}", response_model=GenerationJobItem)
def get_generation_job_endpoint(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> GenerationJobItem:
    job = store.get_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Generation job not found")
    return generation_job_to_item(job)


@app.post("/api/generation/jobs/{job_id}/import", response_model=ImportJobResponse)
def import_generation_job_endpoint(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> ImportJobResponse:
    try:
        result = import_generation_job(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportJobResponse(**result)


@app.get("/api/visuals/review", response_model=VisualsReviewResponse)
def visuals_review_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    asset_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> VisualsReviewResponse:
    assets = store.list_visual_assets_for_review_extended(asset_type=asset_type, limit=limit)
    items = [visual_to_item(a) for a in assets]
    return VisualsReviewResponse(items=items, count=len(items))


@app.post("/api/visuals/approve", response_model=VisualStatusResponse)
def approve_visuals_endpoint(
    body: VisualIdsRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> VisualStatusResponse:
    updated = store.approve_visual_assets(body.asset_ids)
    return VisualStatusResponse(updated=updated, count=len(updated))


@app.post("/api/visuals/reject", response_model=VisualStatusResponse)
def reject_visuals_endpoint(
    body: VisualIdsRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> VisualStatusResponse:
    updated = store.reject_visual_assets(body.asset_ids)
    return VisualStatusResponse(updated=updated, count=len(updated))


@app.post("/api/workbench/find-source", response_model=WorkbenchFindResponse)
def workbench_find_source(
    body: WorkbenchFindRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> WorkbenchFindResponse:
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query is required")
    candidates = find_source_candidates(store, body.query, limit=body.limit)
    items = [candidate_to_item(c) for c in candidates]
    return WorkbenchFindResponse(items=items, count=len(items))


@app.post("/api/workbench/create-original", response_model=GenerationJobItem)
def workbench_create_original(
    body: WorkbenchCreateRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> GenerationJobItem:
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query is required")
    try:
        result = create_freeform_job(
            store,
            body.query,
            image_count=body.image_count,
            video_count=body.video_count,
            style=body.style,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return generation_job_to_item(result.job)


@app.post("/api/workbench/create-from-candidate")
def workbench_create_from_candidate_endpoint(
    body: WorkbenchCreateFromCandidateRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    ref = store.get_reference_by_id(body.reference_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")
    from discovery.workbench import SourceCandidate

    candidate = SourceCandidate(
        reference_id=body.reference_id,
        title=ref.title,
        url=ref.url,
        platform=ref.platform,
        external_id=ref.external_id,
        duration_sec=ref.duration_sec,
    )
    result = workbench_create_from_candidate(
        store,
        candidate,
        source_mode=body.source_mode,
        image_count=body.image_count,
        video_count=body.video_count,
    )
    payload = {
        "source": source_media_to_item(result["source"].source).model_dump(),
        "job": generation_job_to_item(result["job"].job).model_dump() if result["job"] else None,
    }
    return payload


@app.get("/api/source-media/{source_media_id}", response_model=SourceMediaResponse)
def get_source_media_endpoint(
    source_media_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> SourceMediaResponse:
    source = store.get_source_media(source_media_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source media not found")
    item = source_media_to_item(source)
    return SourceMediaResponse(
        item=item,
        reuse_report=item.reuse_report or ReuseReportItem(),
        risk_scores=item.risk_scores or RiskScoresItem(),
    )


@app.get("/api/visuals/approved", response_model=VisualsReviewResponse)
def list_approved_visuals_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    limit: int = Query(100, ge=1, le=200),
) -> VisualsReviewResponse:
    assets = store.list_approved_visual_assets_global(limit=limit)
    items = [visual_to_item(asset) for asset in assets]
    return VisualsReviewResponse(items=items, count=len(items))


@app.post("/api/source-media/{source_media_id}/acquire")
def acquire_source_endpoint(
    source_media_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = acquire_source_media(store, source_media_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.__dict__


@app.post("/api/source-media/{source_media_id}/segments")
def clip_segment_endpoint(
    source_media_id: int,
    body: SourceSegmentRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        if body.start_sec is None or body.end_sec is None:
            raise ValueError("start_sec and end_sec required")
        result = clip_source_segment(
            store,
            source_media_id,
            start_sec=body.start_sec,
            end_sec=body.end_sec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/api/production/projects")
def create_project_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = create_production_project(
            store,
            title=body.get("title", "Untitled Short"),
            niche=body.get("niche"),
            origin_type=body.get("origin_type", "reference"),
            reference_id=body.get("reference_id"),
            source_media_id=body.get("source_media_id"),
            source_segment_id=body.get("source_segment_id"),
            concept_id=body.get("concept_id"),
            format_profile=body.get("format_profile", "audio_visuals"),
            hook_text=body.get("hook_text"),
            caption_preset=body.get("caption_preset", "viral_bold"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = store.get_production_project(result.project_id)
    return project.__dict__ if project else result.__dict__


@app.get("/api/production/projects")
def list_projects_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    projects = store.list_production_projects(status=status, limit=limit)
    return {"items": [p.__dict__ for p in projects], "count": len(projects)}


@app.get("/api/videos/library")
def list_video_library_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    include_missing: bool = Query(False),
    limit: int = Query(100, ge=1, le=200),
):
    items = build_video_library(
        store,
        root=project_root(),
        include_missing_legacy=include_missing,
        limit=limit,
    )
    return {
        "items": [item.to_dict() for item in items],
        "count": len(items),
        "summary": library_summary(items),
    }


@app.post("/api/videos/import")
def import_videos_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    slug = body.get("slug")
    slugs = [slug] if slug else body.get("slugs")
    try:
        payload = import_videos_to_site(
            store,
            root=project_root(),
            slugs=slugs,
            rebuild_catalog=bool(body.get("rebuild_catalog", True)),
            copy_files=bool(body.get("copy_files", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


@app.post("/api/videos/prune")
def prune_videos_catalog_endpoint():
    legacy = prune_missing_legacy_catalog(project_root())
    return {"legacy_catalog": legacy}


@app.post("/api/videos/library/update")
def update_video_library_item_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    source = str(body.get("source") or "").strip()
    if not source:
        raise HTTPException(status_code=422, detail="source is required")
    try:
        item = update_video_library_item(
            store,
            root=project_root(),
            source=source,
            library_id=body.get("library_id"),
            project_id=body.get("project_id"),
            legacy_id=body.get("legacy_id"),
            speaker=body.get("speaker"),
            media_kind=body.get("media_kind"),
            remember_speaker=bool(body.get("remember_speaker", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item.to_dict()}


@app.post("/api/videos/library/link-post")
def link_video_post_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    from discovery.publishing.links import link_video_post

    account_id = body.get("account_id")
    platform_url = str(body.get("platform_url") or "").strip()
    slug = str(body.get("slug") or "").strip()
    title = str(body.get("title") or slug or "Video").strip()
    if not account_id or not platform_url or not slug:
        raise HTTPException(status_code=422, detail="account_id, platform_url, and slug are required")
    try:
        result = link_video_post(
            store,
            account_id=int(account_id),
            platform_url=platform_url,
            slug=slug,
            title=title,
            project_id=body.get("project_id"),
            output_path=body.get("output_path"),
            niche=body.get("niche"),
            origin_type=str(body.get("origin_type") or body.get("source") or "legacy"),
            format_profile=str(body.get("format_profile") or "source_video_visuals"),
            refresh_analytics=bool(body.get("refresh_analytics", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/api/videos/library/delete")
def delete_video_library_item_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    source = str(body.get("source") or "").strip()
    if not source:
        raise HTTPException(status_code=422, detail="source is required")
    try:
        deleted = delete_video_library_item(
            store,
            root=project_root(),
            source=source,
            library_id=body.get("library_id"),
            project_id=body.get("project_id"),
            legacy_id=body.get("legacy_id"),
            slug=body.get("slug"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": deleted}


@app.get("/api/shorts/build/defaults")
def shorts_build_defaults_endpoint():
    return build_defaults(project_root())


@app.post("/api/shorts/build")
def shorts_build_endpoint(body: dict):
    slug = str(body.get("slug") or "").strip()
    if slug and not body.get("rerender"):
        existing = project_root() / "downloads" / "motivational" / slug / "output" / f"{slug}-motivation.mp4"
        if existing.is_file():
            raise HTTPException(status_code=409, detail=f"Short already exists for slug '{slug}'. Use rerender=true to rebuild.")
    try:
        return start_motivation_build(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/shorts/build/{job_id}")
def shorts_build_status_endpoint(job_id: str):
    job = read_job(job_id, project_root())
    if not job:
        raise HTTPException(status_code=404, detail="Build job not found")
    return job


@app.get("/api/commands/status")
def commands_status_endpoint():
    return {"cursor_agent_available": agent_available()}


@app.get("/api/commands")
def list_commands_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
    limit: int = Query(50, ge=1, le=200),
):
    return {"items": list_command_jobs(store, limit=limit)}


@app.post("/api/commands")
def submit_command_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    command = str(body.get("command") or body.get("user_command") or "").strip()
    if not command:
        raise HTTPException(status_code=422, detail="command is required")
    try:
        return submit_command(
            store,
            user_command=command,
            video_id=body.get("video_id"),
            parent_video_id=body.get("parent_video_id"),
            session_id=body.get("session_id"),
            batch_count=body.get("batch_count"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/commands/{job_key}")
def get_command_endpoint(
    job_key: str,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    job = get_command_job(store, job_key)
    if not job:
        raise HTTPException(status_code=404, detail="Command job not found")
    return job


@app.get("/api/library/videos")
def library_videos_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    limit: int = Query(100, ge=1, le=500),
    speaker: str | None = None,
    topic: str | None = None,
    status: str | None = None,
    used: bool | None = Query(None),
):
    return {"items": list_videos(store, limit=limit, speaker=speaker, topic=topic, status=status, used=used)}


@app.get("/api/library/videos/{video_id}")
def library_video_detail_endpoint(
    video_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    prune_missing: bool = Query(False),
):
    if prune_missing:
        prune_missing_components(store, video_id)
    video = get_video(store, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Production video not found")
    return video


@app.post("/api/library/videos/{video_id}/prune-components")
def library_prune_components_endpoint(
    video_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    removed = prune_missing_components(store, video_id)
    video = get_video(store, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Production video not found")
    return {"removed": removed, "video": video}


@app.get("/api/library/speakers")
def library_speakers_endpoint():
    return {"items": [name for name, _hints in KNOWN_SPEAKERS]}


@app.post("/api/library/videos/{video_id}/speaker")
def library_update_speaker_endpoint(
    video_id: int,
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    speaker = str(body.get("speaker") or "").strip()
    if not speaker:
        raise HTTPException(status_code=422, detail="speaker is required")
    remember = bool(body.get("remember_correction", True))
    try:
        return update_video_speaker(
            store,
            video_id,
            speaker,
            remember=remember,
            corrected_by=str(body.get("corrected_by") or "user"),
            notes=body.get("notes"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/library/videos/{video_id}/trim")
def library_trim_video_endpoint(
    video_id: int,
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    from discovery.library_trim import trim_library_video

    mode = str(body.get("mode") or "new_version").strip().lower()
    if mode not in {"override", "new_version"}:
        raise HTTPException(status_code=422, detail="mode must be override or new_version")
    try:
        start_sec = float(body["start_sec"])
        end_sec = float(body["end_sec"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="start_sec and end_sec are required numbers") from exc
    try:
        return trim_library_video(
            store,
            video_id,
            start_sec=start_sec,
            end_sec=end_sec,
            mode=mode,
            change_summary=body.get("change_summary"),
            version_label=body.get("version_label"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/library/videos/{video_id}/posting-status")
def library_update_posting_status_endpoint(
    video_id: int,
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
):
    owner = str(body.get("owner") or os.environ.get("PUBLISHING_OWNER") or "chris").strip().lower()
    try:
        return update_video_posting_status(
            store,
            video_id,
            owner=owner,
            tiktok=body.get("tiktok") if "tiktok" in body else None,
            youtube=body.get("youtube") if "youtube" in body else None,
            instagram=body.get("instagram") if "instagram" in body else None,
            marked_by=str(body.get("marked_by") or "user"),
        )
    except ValueError as exc:
        status = 422 if "owner must be" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/api/library/check-reuse")
def library_check_reuse_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    return check_reuse(
        store,
        source_url=body.get("source_url"),
        source_external_id=body.get("source_external_id") or body.get("source_id"),
        source_platform=body.get("source_platform"),
        source_start_sec=body.get("source_start_sec"),
        source_end_sec=body.get("source_end_sec"),
        transcript=body.get("transcript"),
        speaker=body.get("speaker"),
        topic=body.get("topic"),
    )


@app.post("/api/library/import")
async def library_import_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    _: Annotated[None, Depends(require_internal_key)],
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    speaker: str | None = Form(default=None),
    topic: str | None = Form(default=None),
    extract_audio: bool = Form(default=True),
    transcribe: bool = Form(default=False),
):
    suffix = Path(file.filename or "upload.mp4").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        video = import_uploaded_video(
            store,
            upload_path=tmp_path,
            title=title,
            speaker=speaker,
            topic=topic,
            extract_audio=extract_audio,
            transcribe=transcribe,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return video


@app.get("/api/library/combinations/catalog")
def combinations_catalog_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    owner: str | None = None,
    prune_missing: bool = Query(False),
):
    try:
        return catalog_payload(store, owner=owner, prune_missing=prune_missing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/library/combinations/sync-catalog")
def combinations_sync_catalog_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    body: dict | None = None,
):
    body = body or {}
    pruned = prune_stale_combination_catalog(store) if body.get("prune_missing", True) else {}
    synced = sync_visual_packs(store)
    return {"synced": len(synced), "pruned": pruned}


@app.post("/api/library/combinations/status")
def combinations_status_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    owner = body.get("owner")
    audio_id = body.get("audio_component_id")
    if not owner or audio_id is None:
        raise HTTPException(status_code=400, detail="owner and audio_component_id are required")
    try:
        return combination_status(store, owner=str(owner), audio_component_id=int(audio_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/library/combinations/render")
def combinations_render_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    owner = body.get("owner")
    audio_id = body.get("audio_component_id")
    pack_id = body.get("visual_pack_id")
    if not owner or audio_id is None or pack_id is None:
        raise HTTPException(
            status_code=400,
            detail="owner, audio_component_id, and visual_pack_id are required",
        )
    try:
        return render_combination(
            store,
            owner=str(owner),
            audio_component_id=int(audio_id),
            visual_pack_id=int(pack_id),
            audio_start_sec=body.get("audio_start_sec"),
            audio_end_sec=body.get("audio_end_sec"),
            segment_length=float(body["segment_length"]) if body.get("segment_length") is not None else None,
            grade=body.get("apply_grade", True) is not False,
            version_label=body.get("version_label"),
            change_summary=body.get("change_summary"),
            force_usage=bool(body.get("force") or body.get("use_anyway")),
            slug=body.get("slug"),
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/library/combinations/import-usage")
def combinations_import_usage_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    owner = body.get("owner")
    if not owner:
        raise HTTPException(status_code=400, detail="owner is required")
    try:
        return import_usage_from_videos(
            store,
            owner=str(owner),
            video_ids=body.get("video_ids"),
            all_videos=bool(body.get("all_videos")),
            dry_run=bool(body.get("dry_run")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/library/shared-sync/status")
def shared_sync_status_endpoint():
    return sync_status()


@app.post("/api/library/shared-sync/pull-import")
def shared_sync_pull_import_endpoint(
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    dry_run = bool(body.get("dry_run"))
    auto_only = bool(body.get("auto_only"))
    force = bool(body.get("force"))

    if auto_only and not force:
        try:
            result = maybe_auto_pull_import(store, force=False)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None:
            return {
                "skipped": True,
                "reason": "not_due",
                "status": sync_status(),
            }
        return {**result, "skipped": False}

    skip_pull = bool(body.get("skip_pull"))
    try:
        return pull_and_import(store, skip_pull=skip_pull, dry_run=dry_run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/production/projects/{project_id}")
def get_project_endpoint(
    project_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    project = store.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.__dict__


@app.post("/api/production/projects/{project_id}/timeline")
def build_timeline_endpoint(
    project_id: int,
    body: dict,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        timeline = build_project_timeline(
            store,
            project_id,
            visual_asset_ids=body.get("visual_asset_ids"),
            duration_sec=body.get("duration_sec"),
            pacing=body.get("pacing", "balanced"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline


@app.post("/api/production/projects/{project_id}/render")
def render_project_endpoint(
    project_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = render_project(store, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.__dict__


@app.post("/api/production/projects/{project_id}/approve")
def approve_project_endpoint(
    project_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = approve_project(store, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.__dict__


@app.post("/api/production/projects/{project_id}/reject")
def reject_project_endpoint(
    project_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = reject_project(store, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.__dict__


@app.post("/api/production/projects/{project_id}/send-to-review")
def send_to_review_endpoint(
    project_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = send_project_to_review(store, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.__dict__


def _publishing_account_item(store: DiscoveryStore, account) -> PublishingAccountItem:
    return PublishingAccountItem(
        id=account.id,
        platform=account.platform,
        display_name=account.display_name,
        owner=getattr(account, "owner", None) or "chris",
        platform_account_id=account.platform_account_id,
        username=account.username,
        niche=account.niche,
        enabled=account.enabled,
        auth_status=account.auth_status,
        posting_available=account.posting_available,
        audit_note=account.audit_note,
        token_expires_at=account.token_expires_at,
        created_at=account.created_at,
        last_verified_at=account.last_verified_at,
    )


def _publishing_job_item(store: DiscoveryStore, job) -> PublishingJobItem:
    account = store.get_publishing_account(job.account_id)
    return PublishingJobItem(
        id=job.id,
        production_project_id=job.production_project_id,
        account_id=job.account_id,
        platform=job.platform,
        title=job.title,
        caption=job.caption,
        hashtags=job.hashtags,
        scheduled_at=job.scheduled_at,
        timezone=job.timezone,
        status=job.status,
        platform_post_id=job.platform_post_id,
        platform_url=job.platform_url,
        error_message=job.error_message,
        attempts=job.attempts,
        created_at=job.created_at,
        published_at=job.published_at,
        account_display_name=account.display_name if account else None,
    )


@app.get("/api/config/publishing-owner")
def publishing_owner_endpoint():
    from discovery.config import publishing_owner

    return {"owner": publishing_owner()}


@app.get("/api/config/publishing-setup")
def publishing_setup_endpoint(store: Annotated[DiscoveryStore, Depends(get_store)]):
    from discovery.publishing.setup import publishing_setup_report

    return publishing_setup_report(store)


@app.get("/api/command-center")
def command_center_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    owner: str | None = None,
):
    from discovery.command_center import build_command_center

    return build_command_center(store, owner_filter=owner)


@app.get("/api/accounts", response_model=PublishingAccountsResponse)
def list_accounts_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    platform: str | None = None,
    owner: str | None = None,
) -> PublishingAccountsResponse:
    accounts = store.list_publishing_accounts(platform=platform, owner=owner)
    items = [_publishing_account_item(store, a) for a in accounts]
    return PublishingAccountsResponse(items=items, count=len(items))


@app.post("/api/accounts/{platform}/connect", response_model=ConnectAccountResponse)
def connect_account_endpoint(
    platform: str,
    body: ConnectAccountRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> ConnectAccountResponse:
    if platform not in {"youtube", "tiktok", "instagram", "facebook"}:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")
    display_name = (body.display_name or "").strip() or f"{(body.owner or 'local').title()} {platform.title()}"
    try:
        result = start_account_connect(
            store,
            platform,
            display_name=display_name,
            niche=body.niche,
            redirect_uri=body.redirect_uri,
            owner=body.owner,
        )
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Platform credentials missing") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConnectAccountResponse(
        platform=result.platform,
        auth_url=result.auth_url,
        state=result.state,
        instructions=result.instructions,
    )


@app.post("/api/accounts/connect/complete")
def complete_connect_endpoint(
    body: CompleteConnectRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        account_id = complete_account_connect(store, state=body.state, code=body.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    account = store.get_publishing_account(account_id)
    return _publishing_account_item(store, account) if account else {"id": account_id}


@app.post("/api/accounts/mock/{platform}")
def create_mock_account_endpoint(
    platform: str,
    body: ConnectAccountRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        account_id = import_mock_account(
            store,
            platform=platform,
            display_name=body.display_name,
            username=body.display_name,
            niche=body.niche,
        )
        verify_publishing_account(store, account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = store.get_publishing_account(account_id)
    return _publishing_account_item(store, account) if account else {"id": account_id}


@app.delete("/api/accounts/{account_id}")
def delete_account_endpoint(
    account_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    disconnect_account(store, account_id)
    store.delete_publishing_account(account_id)
    return {"deleted": account_id}


@app.post("/api/accounts/{account_id}/verify")
def verify_account_endpoint(
    account_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = verify_publishing_account(store, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@app.post("/api/publishing/jobs", response_model=PublishingJobsResponse)
def create_publishing_jobs_endpoint(
    body: CreatePublishingJobRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> PublishingJobsResponse:
    try:
        results = create_publishing_jobs(
            store,
            production_project_id=body.production_project_id,
            account_ids=body.account_ids,
            title=body.title,
            caption=body.caption,
            hashtags=body.hashtags,
            scheduled_at=body.scheduled_at,
            timezone_name=body.timezone,
            metadata_by_platform=body.metadata_by_platform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_ids = [r.job_id for r in results]
    if body.publish_now and not body.scheduled_at:
        for job_id in job_ids:
            try:
                publish_job(store, job_id)
            except Exception:
                pass
    jobs = [store.get_publishing_job(jid) for jid in job_ids]
    items = [_publishing_job_item(store, j) for j in jobs if j]
    return PublishingJobsResponse(items=items, count=len(items))


@app.get("/api/publishing/jobs", response_model=PublishingJobsResponse)
def list_publishing_jobs_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    status: str | None = None,
    production_project_id: int | None = None,
    limit: int = Query(100, ge=1, le=200),
) -> PublishingJobsResponse:
    jobs = store.list_publishing_jobs(
        status=status,
        production_project_id=production_project_id,
        limit=limit,
    )
    items = [_publishing_job_item(store, j) for j in jobs]
    return PublishingJobsResponse(items=items, count=len(items))


@app.get("/api/publishing/jobs/{job_id}", response_model=PublishingJobItem)
def get_publishing_job_endpoint(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
) -> PublishingJobItem:
    job = store.get_publishing_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")
    return _publishing_job_item(store, job)


@app.post("/api/publishing/jobs/{job_id}/publish")
def publish_job_endpoint(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = publish_job(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.__dict__


@app.post("/api/publishing/jobs/{job_id}/cancel")
def cancel_job_endpoint(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = cancel_publishing_job(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.__dict__


@app.post("/api/publishing/jobs/{job_id}/retry")
def retry_job_endpoint(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        result = retry_publishing_job(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.__dict__


def _analytics_post_item(row: dict) -> AnalyticsPostItem:
    return AnalyticsPostItem(
        publishing_job_id=int(row["publishing_job_id"]),
        production_project_id=int(row["production_project_id"]),
        account_id=int(row["account_id"]),
        platform=str(row["platform"]),
        title=row.get("title"),
        platform_url=row.get("platform_url"),
        published_at=row.get("published_at"),
        views=row.get("views"),
        likes=row.get("likes"),
        comments=row.get("comments"),
        performance_score=row.get("performance_score"),
        performance_tier=row.get("performance_tier"),
        velocity_views_per_day=row.get("velocity_views_per_day"),
        views_vs_account_median=row.get("views_vs_account_median"),
        hook_formula=row.get("hook_formula"),
        niche=row.get("niche"),
        snapshot_at=row.get("snapshot_at"),
    )


def _pattern_items(rows: list[dict], label_key: str) -> AnalyticsPatternsResponse:
    items = [
        AnalyticsPatternItem(
            label=str(row[label_key]),
            post_count=int(row["post_count"]),
            avg_performance_score=float(row["avg_performance_score"]),
            avg_views=int(row.get("avg_views") or 0),
            breakout_count=int(row.get("breakout_count") or 0),
        )
        for row in rows
    ]
    return AnalyticsPatternsResponse(items=items, count=len(items))


@app.get("/api/analytics/overview", response_model=AnalyticsOverview)
def analytics_overview(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    platform: str | None = None,
    account_id: int | None = None,
    owner: str | None = None,
    niche: str | None = None,
):
    data = store.analytics_overview(platform=platform, account_id=account_id, owner=owner, niche=niche)
    return AnalyticsOverview(**data)


@app.get("/api/analytics/board")
def analytics_board_endpoint(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    owner: str | None = None,
    include_live: bool = Query(True),
):
    from discovery.analytics.account_summary import owner_analytics_board

    return owner_analytics_board(store, owner=owner, include_live=include_live)


@app.get("/api/analytics/posts", response_model=AnalyticsPostsResponse)
def analytics_posts(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    platform: str | None = None,
    account_id: int | None = None,
    owner: str | None = None,
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    rows = store.list_analytics_posts_with_latest(
        niche=niche,
        account_id=account_id,
        platform=platform,
        owner=owner,
        limit=limit,
    )
    items = [_analytics_post_item(row) for row in rows]
    return AnalyticsPostsResponse(items=items, count=len(items))


@app.get("/api/analytics/posts/{job_id}")
def analytics_post_detail(
    job_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    import json

    job = store.get_publishing_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")
    features_row = store.get_analytics_post_features(job_id)
    features = json.loads(features_row.features_json) if features_row else {}
    latest = store.get_latest_analytics_snapshot(job_id)
    history = store.list_analytics_snapshots_for_job(job_id)
    score_data = {}
    if latest:
        score_data = {
            "performance_score": latest.performance_score,
            "performance_tier": latest.performance_tier,
            "views_vs_account_median": latest.views_vs_account_median,
            "velocity_views_per_day": latest.velocity_views_per_day,
        }
    return {
        "job": job.__dict__,
        "features": features,
        "latest_snapshot": latest.__dict__ if latest else None,
        "history": [s.__dict__ for s in history],
        "performance_signals": performance_signals(score_data, features),
    }


@app.post("/api/analytics/refresh", response_model=AnalyticsRefreshResponse)
def analytics_refresh_endpoint(
    body: AnalyticsRefreshRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    results = refresh_analytics(
        store,
        account_id=body.account_id,
        job_id=body.job_id,
        limit=body.limit,
        force=body.force,
    )
    refreshed = sum(1 for r in results if r.refreshed)
    skipped = sum(1 for r in results if not r.refreshed and not r.error)
    errors = sum(1 for r in results if r.error)
    return AnalyticsRefreshResponse(
        refreshed=refreshed,
        skipped=skipped,
        errors=errors,
        results=[r.__dict__ for r in results],
    )


@app.get("/api/analytics/hooks", response_model=AnalyticsPatternsResponse)
def analytics_hooks(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    rows = store.list_analytics_posts_with_latest(niche=niche, limit=limit)
    return _pattern_items(aggregate_hooks(rows), "hook_formula")


@app.get("/api/analytics/topics", response_model=AnalyticsPatternsResponse)
def analytics_topics(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    rows = store.list_analytics_posts_with_latest(niche=niche, limit=limit)
    return _pattern_items(aggregate_topics(rows), "topic")


@app.get("/api/analytics/formats", response_model=AnalyticsPatternsResponse)
def analytics_formats(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    rows = store.list_analytics_posts_with_latest(niche=niche, limit=limit)
    return _pattern_items(aggregate_formats(rows), "format")


@app.get("/api/analytics/visuals", response_model=AnalyticsPatternsResponse)
def analytics_visuals(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    rows = store.list_analytics_posts_with_latest(niche=niche, limit=limit)
    return _pattern_items(aggregate_visuals(rows), "visual_style")


@app.get("/api/analytics/accounts", response_model=AnalyticsPatternsResponse)
def analytics_accounts(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    rows = store.list_analytics_posts_with_latest(niche=niche, limit=limit)
    account_rows = aggregate_accounts(rows)
    for row in account_rows:
        row["account_id"] = str(row.pop("account_id"))
    return _pattern_items(account_rows, "account_id")


@app.get("/api/analytics/performance-profile", response_model=PerformanceProfileResponse)
def analytics_performance_profile(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    niche: str = Query(...),
    account_id: int | None = None,
):
    profile = build_performance_profile(store, niche=niche, account_id=account_id)
    return PerformanceProfileResponse(niche=niche, account_id=account_id, profile=profile)


@app.get("/api/analytics/projects/{project_id}", response_model=ProjectAnalyticsResponse)
def project_analytics(
    project_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    import json

    project = store.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    jobs = store.list_published_jobs_for_project(project_id)
    features: dict = {}
    latest_metrics = None
    snapshots: list[dict] = []
    signals: list[str] = []
    job_items: list[PublishingJobItem] = []
    for job in jobs:
        account = store.get_publishing_account(job.account_id)
        job_items.append(
            PublishingJobItem(
                id=job.id,
                production_project_id=job.production_project_id,
                account_id=job.account_id,
                platform=job.platform,
                title=job.title,
                status=job.status,
                platform_post_id=job.platform_post_id,
                platform_url=job.platform_url,
                published_at=job.published_at,
                account_display_name=account.display_name if account else None,
            )
        )
        feat_row = store.get_analytics_post_features(job.id)
        if feat_row and not features:
            features = json.loads(feat_row.features_json)
        latest = store.get_latest_analytics_snapshot(job.id)
        if latest:
            latest_metrics = latest.__dict__
            score_data = {
                "performance_score": latest.performance_score,
                "performance_tier": latest.performance_tier,
                "views_vs_account_median": latest.views_vs_account_median,
                "velocity_views_per_day": latest.velocity_views_per_day,
            }
            signals = performance_signals(score_data, features)
            snapshots.extend([s.__dict__ for s in store.list_analytics_snapshots_for_job(job.id)])
    return ProjectAnalyticsResponse(
        production_project_id=project_id,
        features=features,
        latest_metrics=latest_metrics,
        snapshots=snapshots,
        performance_signals=signals,
        publishing_jobs=job_items,
    )


def _pilot_item_response(store: DiscoveryStore, item) -> PilotBatchItemResponse:
    import json

    refresh_item_progress(store, item.id)
    item = store.get_pilot_batch_item(item.id)
    stages_raw = json.loads(item.stages_json or "{}") if item else {}
    stages = {
        k: PilotStageItem(
            status=v.get("status", "pending"),
            message=v.get("message", ""),
            entity_id=v.get("entity_id"),
        )
        for k, v in stages_raw.items()
    }
    return PilotBatchItemResponse(
        id=item.id,
        batch_id=item.batch_id,
        sort_order=item.sort_order,
        slot_label=item.slot_label,
        strategy=item.strategy,
        format_profile=item.format_profile,
        status=item.status,
        stages=stages,
        error_stage=item.error_stage,
        error_message=item.error_message,
        notes=item.notes,
        reference_id=item.reference_id,
        source_media_id=item.source_media_id,
        generation_job_id=item.generation_job_id,
        production_project_id=item.production_project_id,
        publishing_job_id=item.publishing_job_id,
    )


def _pilot_batch_response(store: DiscoveryStore, batch) -> PilotBatchResponse:
    items = store.list_pilot_batch_items(batch.id)
    return PilotBatchResponse(
        id=batch.id,
        slug=batch.slug,
        name=batch.name,
        niche=batch.niche,
        account_id=batch.account_id,
        batch_size=batch.batch_size,
        status=batch.status,
        created_at=batch.created_at,
        items=[_pilot_item_response(store, i) for i in items],
    )


@app.get("/api/preflight", response_model=PreflightResponse)
def preflight_endpoint(store: Annotated[DiscoveryStore, Depends(get_store)]):
    data = run_preflight(store)
    groups = {
        key: [PreflightCheckItem(**c) for c in items]
        for key, items in data["groups"].items()
    }
    return PreflightResponse(summary=data["summary"], groups=groups, project_root=data["project_root"])


@app.get("/api/pilot/batches", response_model=PilotBatchesResponse)
def list_pilot_batches(
    store: Annotated[DiscoveryStore, Depends(get_store)],
    limit: int = Query(10, ge=1, le=50),
):
    batches = store.list_pilot_batches(limit=limit)
    items = [_pilot_batch_response(store, b) for b in batches]
    return PilotBatchesResponse(items=items, count=len(items))


@app.post("/api/pilot/batches", response_model=PilotBatchResponse)
def create_pilot_batch_endpoint(
    body: CreatePilotBatchRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    batch_id = create_pilot_batch(
        store,
        name=body.name,
        niche=body.niche,
        account_id=body.account_id,
        batch_size=body.batch_size,
        use_first_batch_mix=body.use_first_batch_mix,
    )
    batch = store.get_pilot_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=500, detail="Failed to create pilot batch")
    return _pilot_batch_response(store, batch)


@app.get("/api/pilot/batches/{batch_id}", response_model=PilotBatchResponse)
def get_pilot_batch_endpoint(
    batch_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    batch = store.get_pilot_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Pilot batch not found")
    return _pilot_batch_response(store, batch)


@app.post("/api/pilot/run-pending", response_model=RunPilotPendingResponse)
def run_pilot_pending_endpoint(
    body: RunPilotPendingRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    report = run_pending_pilot_tasks(
        store,
        batch_id=body.batch_id,
        limit=body.limit,
        live_publish=body.live_publish,
    )
    return RunPilotPendingResponse(
        tasks=[t.__dict__ for t in report.tasks],
        human_required=report.human_required,
        errors=report.errors,
    )


@app.get("/api/pilot/batches/{batch_id}/results")
def pilot_results_endpoint(
    batch_id: int,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    batch = store.get_pilot_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Pilot batch not found")
    return {"items": get_pilot_results(store, batch_id), "disclaimer": "Small sample — not causal proof."}


@app.post("/api/publishing/test-upload")
def test_publish_endpoint(
    body: TestPublishRequest,
    store: Annotated[DiscoveryStore, Depends(get_store)],
):
    try:
        job_result = create_test_publish_job(
            store,
            production_project_id=body.production_project_id,
            account_id=body.account_id,
            title=body.title,
            caption=body.caption,
        )
        if body.live:
            result = publish_test_upload(store, job_result.job_id, live=True)
            return {"job": job_result.__dict__, "publish": result.__dict__, "live": True}
        return {
            "job": job_result.__dict__,
            "message": "Test job created (private). Set live=true to upload.",
            "live": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
