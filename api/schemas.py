"""API response models for discovery endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NicheTag(BaseModel):
    niche: str
    relevance_score: float
    assignment_source: str


class ReferenceMetrics(BaseModel):
    virality_score: float | None = None
    age_hours: float | None = None
    age_days: float | None = None
    views_per_day: float | None = None
    views_per_hour: float | None = None
    like_ratio: float | None = None
    comment_ratio: float | None = None


class ReferenceItem(BaseModel):
    id: int
    platform: str
    external_id: str
    title: str
    channel: str | None = None
    url: str
    thumbnail_url: str | None = None
    published_at: str | None = None
    age_label: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    virality_score: float | None = None
    internal_fit_score: float | None = None
    internal_fit_note: str | None = None
    niches: list[NicheTag] = Field(default_factory=list)
    production_asset: bool = False
    has_analysis: bool = False
    analysis_count: int = 0
    concepts_generated: int = 0
    concepts_approved: int = 0
    exhausted: bool = False
    metrics: ReferenceMetrics | None = None


class NicheCoverageItem(BaseModel):
    niche: str
    reference_count: int
    enabled: bool = True


class DiscoveryStats(BaseModel):
    total_references: int
    references_added_today: int
    high_virality_references: int
    searches_today: int
    detail_requests_today: int
    discovery_runs: int
    production_assets: int
    concepts_ready: int
    visuals_waiting_review: int
    niche_coverage: list[NicheCoverageItem] = Field(default_factory=list)


class ReferencesResponse(BaseModel):
    items: list[ReferenceItem]
    count: int


class ScanRequest(BaseModel):
    query: str
    niche: str | None = None
    limit: int = Field(default=25, ge=1, le=100)
    force: bool = False


class ScanResponse(BaseModel):
    query: str
    ids_found: int = 0
    ids_new: int = 0
    ids_updated: int = 0
    ids_existing: int = 0
    ids_skipped_refresh: int = 0
    detail_requests: int = 0
    searches_executed: int = 0
    searches_skipped: int = 0
    skipped_cooldown: bool = False


class DiscoverRequest(BaseModel):
    max_searches: int = Field(default=10, ge=1, le=50)
    force: bool = False


class DiscoverResponse(BaseModel):
    searches_executed: int = 0
    searches_skipped_cooldown: int = 0
    searches_skipped_limit: int = 0
    searches_skipped_niche_cap: int = 0
    ids_new: int = 0
    ids_updated: int = 0
    ids_existing: int = 0
    detail_requests: int = 0
    skipped_terms: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    reanalyze: bool = False


class AnalysisItem(BaseModel):
    id: int
    reference_id: int
    analyzed_at: str
    provider: str
    model: str | None = None
    analysis_version: str
    observed: dict[str, Any] = Field(default_factory=dict)
    inferred: dict[str, Any] = Field(default_factory=dict)
    hook_type: str | None = None
    emotional_trigger: str | None = None
    pacing_style: str | None = None
    story_structure: str | None = None
    visual_mood: str | None = None
    transferable_patterns: str = ""
    avoid_copying: str = ""
    analysis_json: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False


class AnalysisResponse(BaseModel):
    item: AnalysisItem | None = None
    items: list[AnalysisItem] = Field(default_factory=list)


class GenerateConceptsRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    niche: str | None = None


class ConceptItem(BaseModel):
    id: int
    reference_id: int
    reference_title: str | None = None
    reference_virality_score: float | None = None
    analysis_id: int
    niche: str | None = None
    title: str
    hook_idea: str | None = None
    visual_premise: str | None = None
    setting: str | None = None
    subject: str | None = None
    camera_movement: str | None = None
    mood: str | None = None
    story_premise: str | None = None
    variation_family: str | None = None
    originality_notes: str | None = None
    status: str
    production_asset: bool = False
    created_at: str


class ConceptsResponse(BaseModel):
    items: list[ConceptItem]
    count: int


class GenerateConceptsResponse(BaseModel):
    reference_id: int
    requested: int
    stored: int
    rejected_similar: int
    skipped_exhaustion: int
    concepts: list[ConceptItem]


class ConceptIdsRequest(BaseModel):
    concept_ids: list[int] = Field(min_length=1)


class ConceptStatusResponse(BaseModel):
    updated: list[int]
    count: int


class RiskScoresItem(BaseModel):
    monetization_confidence: float = 50.0
    rights_confidence: float = 50.0
    reuse_confidence: float = 0.0
    monetization_level: str = "yellow"
    rights_level: str = "yellow"
    reuse_level: str = "green"
    explanations: dict[str, list[str]] = Field(default_factory=dict)


class PriorUseItem(BaseModel):
    kind: str
    id: str
    title: str
    account: str = ""
    path: str = ""
    score: float = 1.0


class ReuseReportItem(BaseModel):
    seen_as_reference: bool = False
    actually_used_in_content: bool = False
    reuse_confidence: float = 0.0
    prior_uses: list[PriorUseItem] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)


class CreateSourceMediaRequest(BaseModel):
    title: str | None = None
    source_mode: str
    media_type: str | None = None
    reference_id: int | None = None
    platform: str | None = None
    external_id: str | None = None
    url: str | None = None
    local_path: str | None = None
    transcript: str | None = None
    duration_sec: float | None = None


class SourceMediaItem(BaseModel):
    id: int
    title: str
    source_mode: str
    media_type: str
    reference_id: int | None = None
    platform: str | None = None
    external_id: str | None = None
    url: str | None = None
    local_path: str | None = None
    download_status: str | None = None
    download_path: str | None = None
    transcript: str | None = None
    duration_sec: float | None = None
    rights_confidence: float | None = None
    monetization_confidence: float | None = None
    reuse_confidence: float | None = None
    seen_as_reference: bool = False
    actually_used_in_content: bool = False
    production_asset: bool = False
    created_at: str = ""
    risk_scores: RiskScoresItem | None = None
    reuse_report: ReuseReportItem | None = None


class SourceMediaResponse(BaseModel):
    item: SourceMediaItem
    reuse_report: ReuseReportItem
    risk_scores: RiskScoresItem


class SourceSegmentRequest(BaseModel):
    start_sec: float | None = None
    end_sec: float | None = None
    transcript: str | None = None
    local_path: str | None = None


class SourceSegmentItem(BaseModel):
    id: int
    source_media_id: int
    start_sec: float | None = None
    end_sec: float | None = None
    transcript: str | None = None
    local_path: str | None = None


class TranscribeRequest(BaseModel):
    transcript: str | None = None


class CreateGenerationJobRequest(BaseModel):
    origin_type: str = "freeform"
    prompt_summary: str = ""
    image_count: int = Field(default=0, ge=0, le=50)
    video_count: int = Field(default=0, ge=0, le=20)
    style: str | None = None
    aspect_ratio: str | None = "9:16"
    niche: str | None = None
    reference_id: int | None = None
    concept_id: int | None = None
    source_media_id: int | None = None


class GenerationJobItem(BaseModel):
    id: int
    job_key: str
    origin_type: str
    status: str
    image_count: int
    video_count: int
    style: str | None = None
    aspect_ratio: str = "9:16"
    niche: str | None = None
    prompt_summary: str | None = None
    reference_id: int | None = None
    concept_id: int | None = None
    source_media_id: int | None = None
    job_json_path: str | None = None
    cursor_prompt_path: str | None = None
    output_dir: str | None = None
    created_at: str = ""


class GenerationJobsResponse(BaseModel):
    items: list[GenerationJobItem]
    count: int


class ImportJobResponse(BaseModel):
    job_id: int
    imported: int
    skipped: int
    failed: list[str] = Field(default_factory=list)


class VisualAssetItem(BaseModel):
    id: int
    asset_type: str
    status: str
    prompt: str
    niche: str | None = None
    variation_family: str | None = None
    local_path: str | None = None
    media_url: str | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    duration_seconds: float | None = None
    concept_id: int | None = None
    reference_id: int | None = None
    generation_job_id: int | None = None
    production_asset: bool = False
    reject_reason: str | None = None
    generated_at: str | None = None


class VisualsReviewResponse(BaseModel):
    items: list[VisualAssetItem]
    count: int


class VisualIdsRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1)


class VisualStatusResponse(BaseModel):
    updated: list[int]
    count: int


class WorkbenchFindRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class WorkbenchCandidateItem(BaseModel):
    reference_id: int | None = None
    title: str = ""
    url: str = ""
    platform: str = "youtube"
    external_id: str = ""
    transcript_snippet: str = ""
    duration_sec: float | None = None
    virality_score: float | None = None
    reuse_confidence: float = 0.0
    rights_confidence: float = 50.0
    monetization_confidence: float = 50.0
    seen_as_reference: bool = False
    actually_used_in_content: bool = False
    explanations: list[str] = Field(default_factory=list)


class WorkbenchFindResponse(BaseModel):
    items: list[WorkbenchCandidateItem]
    count: int


class WorkbenchCreateRequest(BaseModel):
    query: str
    image_count: int | None = None
    video_count: int | None = None
    style: str | None = None


class WorkbenchCreateFromCandidateRequest(BaseModel):
    reference_id: int
    source_mode: str = "audio"
    image_count: int = 0
    video_count: int = 0


class PublishingAccountItem(BaseModel):
    id: int
    platform: str
    display_name: str
    owner: str = "chris"
    platform_account_id: str | None = None
    username: str | None = None
    niche: str | None = None
    enabled: bool = True
    auth_status: str = "disconnected"
    posting_available: bool = False
    audit_note: str | None = None
    token_expires_at: str | None = None
    created_at: str = ""
    last_verified_at: str | None = None


class PublishingAccountsResponse(BaseModel):
    items: list[PublishingAccountItem]
    count: int


class ConnectAccountRequest(BaseModel):
    display_name: str = ""
    niche: str | None = None
    redirect_uri: str | None = None
    owner: str | None = None


class ConnectAccountResponse(BaseModel):
    platform: str
    auth_url: str
    state: str
    instructions: str = ""


class CompleteConnectRequest(BaseModel):
    state: str
    code: str


class CreatePublishingJobRequest(BaseModel):
    production_project_id: int
    account_ids: list[int] = Field(min_length=1)
    title: str | None = None
    caption: str | None = None
    hashtags: str | None = None
    scheduled_at: str | None = None
    timezone: str | None = None
    publish_now: bool = False
    metadata_by_platform: dict[str, dict[str, Any]] | None = None


class PublishingJobItem(BaseModel):
    id: int
    production_project_id: int
    account_id: int
    platform: str
    title: str | None = None
    caption: str | None = None
    hashtags: str | None = None
    scheduled_at: str | None = None
    timezone: str | None = None
    status: str
    platform_post_id: str | None = None
    platform_url: str | None = None
    error_message: str | None = None
    attempts: int = 0
    created_at: str = ""
    published_at: str | None = None
    account_display_name: str | None = None


class PublishingJobsResponse(BaseModel):
    items: list[PublishingJobItem]
    count: int


class AnalyticsOverview(BaseModel):
    total_published_posts: int = 0
    total_views: int = 0
    views_last_7_days: int = 0
    views_last_30_days: int = 0
    average_performance_score: float | None = None
    breakout_count: int = 0
    underperforming_count: int = 0
    posts_with_metrics: int = 0


class VideoLinkPostResponse(BaseModel):
    duplicate: bool = False
    job_id: int
    production_project_id: int
    platform: str
    platform_post_id: str
    platform_url: str
    account_id: int
    account_display_name: str | None = None
    account_owner: str | None = None
    refresh: dict[str, Any] | None = None


class AnalyticsPostItem(BaseModel):
    publishing_job_id: int
    production_project_id: int
    account_id: int
    platform: str
    title: str | None = None
    platform_url: str | None = None
    published_at: str | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    performance_score: float | None = None
    performance_tier: str | None = None
    velocity_views_per_day: float | None = None
    views_vs_account_median: float | None = None
    hook_formula: str | None = None
    niche: str | None = None
    snapshot_at: str | None = None


class AnalyticsPostsResponse(BaseModel):
    items: list[AnalyticsPostItem]
    count: int


class AnalyticsPatternItem(BaseModel):
    label: str
    post_count: int
    avg_performance_score: float
    avg_views: int = 0
    breakout_count: int = 0


class AnalyticsPatternsResponse(BaseModel):
    items: list[AnalyticsPatternItem]
    count: int


class AnalyticsRefreshRequest(BaseModel):
    account_id: int | None = None
    job_id: int | None = None
    force: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class AnalyticsRefreshResponse(BaseModel):
    refreshed: int
    skipped: int
    errors: int
    results: list[dict[str, Any]] = Field(default_factory=list)


class PerformanceProfileResponse(BaseModel):
    niche: str
    account_id: int | None = None
    profile: dict[str, Any] = Field(default_factory=dict)


class ProjectAnalyticsResponse(BaseModel):
    production_project_id: int
    features: dict[str, Any] = Field(default_factory=dict)
    latest_metrics: dict[str, Any] | None = None
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    performance_signals: list[str] = Field(default_factory=list)
    publishing_jobs: list[PublishingJobItem] = Field(default_factory=list)


class PreflightCheckItem(BaseModel):
    label: str
    status: str
    detail: str
    fix_hint: str | None = None


class PreflightResponse(BaseModel):
    summary: dict[str, Any]
    groups: dict[str, list[PreflightCheckItem]]
    project_root: str


class CreatePilotBatchRequest(BaseModel):
    name: str = "First Pilot"
    niche: str
    account_id: int | None = None
    batch_size: int = Field(default=3, ge=1, le=10)
    use_first_batch_mix: bool = True


class PilotStageItem(BaseModel):
    status: str
    message: str = ""
    entity_id: int | None = None


class PilotBatchItemResponse(BaseModel):
    id: int
    batch_id: int
    sort_order: int
    slot_label: str | None = None
    strategy: str
    format_profile: str | None = None
    status: str
    stages: dict[str, PilotStageItem] = Field(default_factory=dict)
    error_stage: str | None = None
    error_message: str | None = None
    notes: str | None = None
    reference_id: int | None = None
    source_media_id: int | None = None
    generation_job_id: int | None = None
    production_project_id: int | None = None
    publishing_job_id: int | None = None


class PilotBatchResponse(BaseModel):
    id: int
    slug: str
    name: str
    niche: str | None = None
    account_id: int | None = None
    batch_size: int
    status: str
    created_at: str
    items: list[PilotBatchItemResponse] = Field(default_factory=list)


class PilotBatchesResponse(BaseModel):
    items: list[PilotBatchResponse]
    count: int


class RunPilotPendingRequest(BaseModel):
    batch_id: int | None = None
    limit: int = Field(default=20, ge=1, le=100)
    live_publish: bool = False


class RunPilotPendingResponse(BaseModel):
    tasks: list[dict[str, Any]]
    human_required: list[str]
    errors: list[str]


class TestPublishRequest(BaseModel):
    production_project_id: int
    account_id: int
    live: bool = False
    title: str | None = None
    caption: str | None = None


def _age_label(metrics: dict[str, Any]) -> str | None:
    age_days = metrics.get("age_days")
    age_hours = metrics.get("age_hours")
    if age_days is not None and age_days >= 1:
        return f"{age_days:.1f}d"
    if age_hours is not None:
        return f"{age_hours:.0f}h"
    return None


def reference_item_from_store(row: dict[str, Any]) -> ReferenceItem:
    ref = row["reference"]
    metrics_raw = row.get("metrics") or {}
    niches = [
        NicheTag(
            niche=n.niche,
            relevance_score=n.relevance_score,
            assignment_source=n.assignment_source,
        )
        for n in row.get("niches", [])
    ]
    metrics = ReferenceMetrics(
        virality_score=metrics_raw.get("virality_score"),
        age_hours=metrics_raw.get("age_hours"),
        age_days=metrics_raw.get("age_days"),
        views_per_day=metrics_raw.get("views_per_day"),
        views_per_hour=metrics_raw.get("views_per_hour"),
        like_ratio=metrics_raw.get("like_ratio"),
        comment_ratio=metrics_raw.get("comment_ratio"),
    )
    return ReferenceItem(
        id=int(ref.id or 0),
        platform=ref.platform,
        external_id=ref.external_id,
        title=ref.title,
        channel=ref.channel,
        url=ref.url,
        thumbnail_url=ref.thumbnail_url,
        published_at=ref.published_at,
        age_label=_age_label(metrics_raw),
        view_count=ref.view_count,
        like_count=ref.like_count,
        comment_count=ref.comment_count,
        virality_score=ref.virality_score,
        niches=niches,
        production_asset=bool(ref.production_asset),
        has_analysis=bool(row.get("has_analysis")),
        analysis_count=int(row.get("analysis_count") or 0),
        concepts_generated=int(row.get("concepts_generated") or 0),
        concepts_approved=int(row.get("concepts_approved") or 0),
        exhausted=bool(row.get("exhausted")),
        metrics=metrics,
        internal_fit_score=row.get("internal_fit_score"),
        internal_fit_note=row.get("internal_fit_note"),
    )

