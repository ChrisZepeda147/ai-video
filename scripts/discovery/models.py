"""Data models for viral reference discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReferenceVideo:
    id: int | None = None
    platform: str = ""
    external_id: str = ""
    url: str = ""
    title: str = ""
    channel: str | None = None
    channel_id: str | None = None
    description: str | None = None
    duration_sec: float | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    published_at: str | None = None
    thumbnail_url: str | None = None
    source_query: str | None = None
    production_asset: bool = False
    virality_score: float | None = None
    last_refreshed_at: str | None = None

    def __post_init__(self) -> None:
        if self.production_asset:
            raise ValueError("Reference videos must never be marked as production assets")

    @property
    def youtube_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.external_id}"


@dataclass
class NicheLink:
    niche: str
    relevance_score: float
    assignment_source: str


@dataclass
class TopReference:
    reference: ReferenceVideo
    metrics: dict[str, Any]
    niches: list[NicheLink]


@dataclass
class ReferenceAnalysis:
    id: int
    reference_id: int
    analyzed_at: str
    provider: str
    model: str | None
    analysis_version: str
    genre: str | None = None
    hook_type: str | None = None
    emotional_trigger: str | None = None
    pacing_style: str | None = None
    tension_structure: str | None = None
    story_structure: str | None = None
    setting_type: str | None = None
    visual_mood: str | None = None
    visual_energy: str | None = None
    camera_style: str | None = None
    lighting_style: str | None = None
    subject_type: str | None = None
    ending_style: str | None = None
    transferable_patterns: str | None = None
    avoid_copying: str | None = None
    analysis_json: dict[str, Any] | None = None


@dataclass
class Concept:
    id: int
    reference_id: int
    analysis_id: int
    niche: str | None
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
    status: str = "generated"
    production_asset: bool = False
    created_at: str = ""


@dataclass
class DiscoveryRunStats:
    ids_found: int = 0
    ids_new: int = 0
    ids_updated: int = 0
    ids_skipped_refresh: int = 0
    ids_existing: int = 0
    detail_requests: int = 0
    niche_links_added: int = 0
    searches_executed: int = 0
    searches_skipped: int = 0

    @property
    def ids_skipped_cooldown(self) -> int:
        """Backward-compatible alias."""
        return self.ids_skipped_refresh


@dataclass
class MultiDiscoverResult:
    searches_executed: int = 0
    searches_skipped_cooldown: int = 0
    searches_skipped_limit: int = 0
    searches_skipped_niche_cap: int = 0
    skipped_terms: list[str] = field(default_factory=list)
    ids_new: int = 0
    ids_updated: int = 0
    ids_existing: int = 0
    detail_requests: int = 0
    run_id: int | None = None


@dataclass
class NicheCoverage:
    niche: str
    reference_count: int


@dataclass
class SourceMedia:
    id: int
    title: str
    media_type: str
    source_mode: str
    reference_id: int | None = None
    platform: str | None = None
    external_id: str | None = None
    url: str | None = None
    local_path: str | None = None
    download_status: str | None = None
    download_path: str | None = None
    raw_local_path: str | None = None
    transcript: str | None = None
    transcript_json: str | None = None
    transcript_hash: str | None = None
    audio_fingerprint: str | None = None
    duration_sec: float | None = None
    rights_confidence: float | None = None
    monetization_confidence: float | None = None
    reuse_confidence: float | None = None
    seen_as_reference: bool = False
    actually_used_in_content: bool = False
    reuse_explanations_json: str | None = None
    risk_explanations_json: str | None = None
    production_asset: bool = False
    created_at: str = ""


@dataclass
class ProductionProject:
    id: int
    slug: str
    title: str
    format_profile: str
    status: str = "draft"
    niche: str | None = None
    origin_type: str | None = "reference"
    reference_id: int | None = None
    source_media_id: int | None = None
    source_segment_id: int | None = None
    concept_id: int | None = None
    duration_sec: float | None = None
    output_path: str | None = None
    timeline_json: str | None = None
    hook_text: str | None = None
    caption_preset: str | None = "viral_bold"
    error_message: str | None = None
    monetization_confidence: float | None = None
    rights_confidence: float | None = None
    reuse_confidence: float | None = None
    risk_explanations_json: str | None = None
    created_at: str = ""
    rendered_at: str | None = None


@dataclass
class PublishingAccount:
    id: int
    platform: str
    display_name: str
    platform_account_id: str | None = None
    username: str | None = None
    niche: str | None = None
    enabled: bool = True
    auth_status: str = "disconnected"
    token_expires_at: str | None = None
    capabilities_json: str | None = None
    posting_available: bool = False
    audit_note: str | None = None
    credentials_ref: str | None = None
    created_at: str = ""
    last_verified_at: str | None = None


@dataclass
class PublishingJob:
    id: int
    production_project_id: int
    account_id: int
    platform: str
    idempotency_key: str
    title: str | None = None
    caption: str | None = None
    hashtags: str | None = None
    metadata_json: str | None = None
    scheduled_at: str | None = None
    timezone: str | None = None
    status: str = "draft"
    platform_post_id: str | None = None
    platform_url: str | None = None
    error_message: str | None = None
    attempts: int = 0
    created_at: str = ""
    published_at: str | None = None


@dataclass
class AnalyticsPostFeatures:
    publishing_job_id: int
    production_project_id: int
    account_id: int
    platform: str
    features_json: str
    niche: str | None = None
    hook_formula: str | None = None
    created_at: str = ""


@dataclass
class AnalyticsPostSnapshot:
    id: int
    publishing_job_id: int
    production_project_id: int
    account_id: int
    platform: str
    snapshot_at: str
    platform_post_id: str | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    watch_time_sec: float | None = None
    avg_watch_duration_sec: float | None = None
    completion_rate: float | None = None
    retention: float | None = None
    followers_gained: int | None = None
    impressions: int | None = None
    click_through_rate: float | None = None
    revenue: float | None = None
    raw_json: str | None = None
    performance_score: float | None = None
    performance_tier: str | None = None
    views_vs_account_median: float | None = None
    velocity_views_per_day: float | None = None


@dataclass
class PerformanceProfile:
    id: int
    niche: str
    profile_json: str
    sample_size: int = 0
    account_id: int | None = None
    updated_at: str = ""


@dataclass
class PilotBatch:
    id: int
    slug: str
    name: str
    niche: str | None = None
    account_id: int | None = None
    batch_size: int = 3
    status: str = "planning"
    config_json: str | None = None
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None


@dataclass
class PilotBatchItem:
    id: int
    batch_id: int
    sort_order: int = 0
    slot_label: str | None = None
    strategy: str = ""
    format_profile: str | None = None
    reference_id: int | None = None
    source_media_id: int | None = None
    concept_id: int | None = None
    generation_job_id: int | None = None
    production_project_id: int | None = None
    publishing_job_id: int | None = None
    status: str = "pending"
    stages_json: str = "{}"
    error_stage: str | None = None
    error_message: str | None = None
    notes: str | None = None
    created_at: str = ""


@dataclass
class SourceSegment:
    id: int
    source_media_id: int
    start_sec: float | None = None
    end_sec: float | None = None
    transcript: str | None = None
    transcript_json: str | None = None
    local_path: str | None = None
    clip_status: str | None = None
    rights_confidence: float | None = None
    monetization_confidence: float | None = None
    reuse_confidence: float | None = None


@dataclass
class GenerationJob:
    id: int
    job_key: str
    origin_type: str
    image_count: int = 0
    video_count: int = 0
    aspect_ratio: str = "9:16"
    status: str = "pending"
    reference_id: int | None = None
    concept_id: int | None = None
    source_media_id: int | None = None
    style: str | None = None
    niche: str | None = None
    prompt_summary: str | None = None
    job_json_path: str | None = None
    cursor_prompt_path: str | None = None
    output_dir: str | None = None
    error_message: str | None = None
    created_at: str = ""
    completed_at: str | None = None
    imported_at: str | None = None


@dataclass
class VisualAsset:
    id: int
    concept_id: int | None
    reference_id: int | None
    niche: str | None = None
    variation_family: str | None = None
    asset_type: str = "image"
    provider: str = ""
    model: str | None = None
    prompt: str = ""
    brief_json: str | None = None
    generation_seed: str | None = None
    local_path: str | None = None
    file_sha256: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    variant_index: int = 1
    generated_at: str | None = None
    status: str = "queued"
    approved_at: str | None = None
    usage_count: int = 0
    max_usage: int | None = None
    last_used_at: str | None = None
    production_asset: bool = False
    reject_reason: str | None = None
    generation_job_id: int | None = None
    source_media_id: int | None = None


@dataclass
class VisualLibraryStats:
    generated: int = 0
    waiting_review: int = 0
    approved: int = 0
    rejected: int = 0
    auto_rejected: int = 0
    production_assets: int = 0
    total_usable_duration: float = 0.0
    average_usage_count: float = 0.0
    by_niche: dict[str, int] = field(default_factory=dict)
    by_family: dict[str, int] = field(default_factory=dict)


@dataclass
class CatalogStats:
    total_references: int
    references_added_today: int
    high_virality_references: int
    discovery_runs: int
    searches_today: int
    detail_requests_today: int
    production_assets: int
    unique_refs_per_search: float
    duplicate_refs_encountered: int
    niche_coverage: list[NicheCoverage]
    youtube_references: int = 0

    # Legacy fields kept for older callers/tests
    @property
    def discovered_today(self) -> int:
        return self.references_added_today


def row_to_analysis(row: Any) -> ReferenceAnalysis:
    import json

    payload = row["analysis_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ReferenceAnalysis(
        id=int(row["id"]),
        reference_id=int(row["reference_id"]),
        analyzed_at=str(row["analyzed_at"]),
        provider=str(row["provider"]),
        model=row["model"],
        analysis_version=str(row["analysis_version"]),
        genre=row["genre"],
        hook_type=row["hook_type"],
        emotional_trigger=row["emotional_trigger"],
        pacing_style=row["pacing_style"],
        tension_structure=row["tension_structure"],
        story_structure=row["story_structure"],
        setting_type=row["setting_type"],
        visual_mood=row["visual_mood"],
        visual_energy=row["visual_energy"],
        camera_style=row["camera_style"],
        lighting_style=row["lighting_style"],
        subject_type=row["subject_type"],
        ending_style=row["ending_style"],
        transferable_patterns=row["transferable_patterns"],
        avoid_copying=row["avoid_copying"],
        analysis_json=payload if isinstance(payload, dict) else {},
    )


def row_to_concept(row: Any) -> Concept:
    return Concept(
        id=int(row["id"]),
        reference_id=int(row["reference_id"]),
        analysis_id=int(row["analysis_id"]),
        niche=row["niche"],
        title=str(row["title"]),
        hook_idea=row["hook_idea"],
        visual_premise=row["visual_premise"],
        setting=row["setting"],
        subject=row["subject"],
        camera_movement=row["camera_movement"],
        mood=row["mood"],
        story_premise=row["story_premise"],
        variation_family=row["variation_family"],
        originality_notes=row["originality_notes"],
        status=str(row["status"]),
        production_asset=bool(row["production_asset"]),
        created_at=str(row["created_at"]),
    )


def row_to_source_media(row: Any) -> SourceMedia:
    keys = row.keys() if hasattr(row, "keys") else []
    return SourceMedia(
        id=int(row["id"]),
        title=str(row["title"]),
        media_type=str(row["media_type"]),
        source_mode=str(row["source_mode"]),
        reference_id=int(row["reference_id"]) if row["reference_id"] is not None else None,
        platform=row["platform"],
        external_id=row["external_id"],
        url=row["url"],
        local_path=row["local_path"],
        download_status=row["download_status"] if "download_status" in keys else None,
        download_path=row["download_path"] if "download_path" in keys else None,
        raw_local_path=row["raw_local_path"] if "raw_local_path" in keys else None,
        transcript=row["transcript"],
        transcript_json=row["transcript_json"] if "transcript_json" in keys else None,
        transcript_hash=row["transcript_hash"],
        audio_fingerprint=row["audio_fingerprint"] if "audio_fingerprint" in keys else None,
        duration_sec=row["duration_sec"],
        rights_confidence=row["rights_confidence"],
        monetization_confidence=row["monetization_confidence"],
        reuse_confidence=row["reuse_confidence"],
        seen_as_reference=bool(row["seen_as_reference"]) if "seen_as_reference" in keys else False,
        actually_used_in_content=bool(row["actually_used_in_content"])
        if "actually_used_in_content" in keys
        else False,
        reuse_explanations_json=row["reuse_explanations_json"]
        if "reuse_explanations_json" in keys
        else None,
        risk_explanations_json=row["risk_explanations_json"]
        if "risk_explanations_json" in keys
        else None,
        production_asset=bool(row["production_asset"]),
        created_at=str(row["created_at"]),
    )


def row_to_publishing_account(row: Any) -> PublishingAccount:
    keys = row.keys() if hasattr(row, "keys") else []
    return PublishingAccount(
        id=int(row["id"]),
        platform=str(row["platform"]),
        display_name=str(row["display_name"]),
        platform_account_id=row["platform_account_id"],
        username=row["username"],
        niche=row["niche"],
        enabled=bool(row["enabled"]),
        auth_status=str(row["auth_status"]),
        token_expires_at=row["token_expires_at"],
        capabilities_json=row["capabilities_json"] if "capabilities_json" in keys else None,
        posting_available=bool(row["posting_available"]) if "posting_available" in keys else False,
        audit_note=row["audit_note"] if "audit_note" in keys else None,
        credentials_ref=row["credentials_ref"] if "credentials_ref" in keys else None,
        created_at=str(row["created_at"]),
        last_verified_at=row["last_verified_at"] if "last_verified_at" in keys else None,
    )


def row_to_publishing_job(row: Any) -> PublishingJob:
    return PublishingJob(
        id=int(row["id"]),
        production_project_id=int(row["production_project_id"]),
        account_id=int(row["account_id"]),
        platform=str(row["platform"]),
        idempotency_key=str(row["idempotency_key"]),
        title=row["title"],
        caption=row["caption"],
        hashtags=row["hashtags"],
        metadata_json=row["metadata_json"],
        scheduled_at=row["scheduled_at"],
        timezone=row["timezone"],
        status=str(row["status"]),
        platform_post_id=row["platform_post_id"],
        platform_url=row["platform_url"],
        error_message=row["error_message"],
        attempts=int(row["attempts"] or 0),
        created_at=str(row["created_at"]),
        published_at=row["published_at"],
    )


def row_to_analytics_post_features(row: Any) -> AnalyticsPostFeatures:
    return AnalyticsPostFeatures(
        publishing_job_id=int(row["publishing_job_id"]),
        production_project_id=int(row["production_project_id"]),
        account_id=int(row["account_id"]),
        platform=str(row["platform"]),
        niche=row["niche"],
        features_json=str(row["features_json"]),
        hook_formula=row["hook_formula"],
        created_at=str(row["created_at"]),
    )


def row_to_analytics_post_snapshot(row: Any) -> AnalyticsPostSnapshot:
    return AnalyticsPostSnapshot(
        id=int(row["id"]),
        publishing_job_id=int(row["publishing_job_id"]),
        production_project_id=int(row["production_project_id"]),
        account_id=int(row["account_id"]),
        platform=str(row["platform"]),
        snapshot_at=str(row["snapshot_at"]),
        platform_post_id=row["platform_post_id"],
        views=row["views"],
        likes=row["likes"],
        comments=row["comments"],
        shares=row["shares"],
        saves=row["saves"],
        watch_time_sec=row["watch_time_sec"],
        avg_watch_duration_sec=row["avg_watch_duration_sec"],
        completion_rate=row["completion_rate"],
        retention=row["retention"],
        followers_gained=row["followers_gained"],
        impressions=row["impressions"],
        click_through_rate=row["click_through_rate"],
        revenue=row["revenue"],
        raw_json=row["raw_json"],
        performance_score=row["performance_score"],
        performance_tier=row["performance_tier"],
        views_vs_account_median=row["views_vs_account_median"],
        velocity_views_per_day=row["velocity_views_per_day"],
    )


def row_to_performance_profile(row: Any) -> PerformanceProfile:
    return PerformanceProfile(
        id=int(row["id"]),
        niche=str(row["niche"]),
        profile_json=str(row["profile_json"]),
        sample_size=int(row["sample_size"] or 0),
        account_id=int(row["account_id"]) if row["account_id"] is not None else None,
        updated_at=str(row["updated_at"]),
    )


def row_to_pilot_batch(row: Any) -> PilotBatch:
    return PilotBatch(
        id=int(row["id"]),
        slug=str(row["slug"]),
        name=str(row["name"]),
        niche=row["niche"],
        account_id=int(row["account_id"]) if row["account_id"] is not None else None,
        batch_size=int(row["batch_size"] or 3),
        status=str(row["status"]),
        config_json=row["config_json"],
        created_at=str(row["created_at"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error_message=row["error_message"],
    )


def row_to_pilot_batch_item(row: Any) -> PilotBatchItem:
    return PilotBatchItem(
        id=int(row["id"]),
        batch_id=int(row["batch_id"]),
        sort_order=int(row["sort_order"] or 0),
        slot_label=row["slot_label"],
        strategy=str(row["strategy"]),
        format_profile=row["format_profile"],
        reference_id=int(row["reference_id"]) if row["reference_id"] is not None else None,
        source_media_id=int(row["source_media_id"]) if row["source_media_id"] is not None else None,
        concept_id=int(row["concept_id"]) if row["concept_id"] is not None else None,
        generation_job_id=int(row["generation_job_id"]) if row["generation_job_id"] is not None else None,
        production_project_id=int(row["production_project_id"]) if row["production_project_id"] is not None else None,
        publishing_job_id=int(row["publishing_job_id"]) if row["publishing_job_id"] is not None else None,
        status=str(row["status"]),
        stages_json=str(row["stages_json"] or "{}"),
        error_stage=row["error_stage"],
        error_message=row["error_message"],
        notes=row["notes"],
        created_at=str(row["created_at"]),
    )


def row_to_production_project(row: Any) -> ProductionProject:
    keys = row.keys() if hasattr(row, "keys") else []
    return ProductionProject(
        id=int(row["id"]),
        slug=str(row["slug"]),
        title=str(row["title"]),
        format_profile=str(row["format_profile"]),
        status=str(row["status"]),
        niche=row["niche"],
        origin_type=row["origin_type"] if "origin_type" in keys else "reference",
        reference_id=int(row["reference_id"]) if "reference_id" in keys and row["reference_id"] is not None else None,
        source_media_id=int(row["source_media_id"]) if row["source_media_id"] is not None else None,
        source_segment_id=int(row["source_segment_id"]) if row["source_segment_id"] is not None else None,
        concept_id=int(row["concept_id"]) if row["concept_id"] is not None else None,
        duration_sec=row["duration_sec"],
        output_path=row["output_path"],
        timeline_json=row["timeline_json"],
        hook_text=row["hook_text"],
        caption_preset=row["caption_preset"],
        error_message=row["error_message"],
        monetization_confidence=row["monetization_confidence"],
        rights_confidence=row["rights_confidence"],
        reuse_confidence=row["reuse_confidence"],
        risk_explanations_json=row["risk_explanations_json"] if "risk_explanations_json" in keys else None,
        created_at=str(row["created_at"]),
        rendered_at=row["rendered_at"] if "rendered_at" in keys else None,
    )


def row_to_generation_job(row: Any) -> GenerationJob:
    keys = row.keys() if hasattr(row, "keys") else []
    return GenerationJob(
        id=int(row["id"]),
        job_key=str(row["job_key"]),
        origin_type=str(row["origin_type"]),
        image_count=int(row["image_count"]),
        video_count=int(row["video_count"]),
        aspect_ratio=str(row["aspect_ratio"]),
        status=str(row["status"]),
        reference_id=int(row["reference_id"]) if row["reference_id"] is not None else None,
        concept_id=int(row["concept_id"]) if row["concept_id"] is not None else None,
        source_media_id=int(row["source_media_id"]) if row["source_media_id"] is not None else None,
        style=row["style"],
        niche=row["niche"],
        prompt_summary=row["prompt_summary"],
        job_json_path=row["job_json_path"],
        cursor_prompt_path=row["cursor_prompt_path"],
        output_dir=row["output_dir"],
        error_message=row["error_message"],
        created_at=str(row["created_at"]),
        completed_at=row["completed_at"] if "completed_at" in keys else None,
        imported_at=row["imported_at"] if "imported_at" in keys else None,
    )


def row_to_visual_asset(row: Any) -> VisualAsset:
    keys = row.keys() if hasattr(row, "keys") else []
    return VisualAsset(
        id=int(row["id"]),
        concept_id=int(row["concept_id"]) if row["concept_id"] is not None else None,
        reference_id=int(row["reference_id"]) if row["reference_id"] is not None else None,
        niche=row["niche"],
        variation_family=row["variation_family"],
        asset_type=str(row["asset_type"]),
        provider=str(row["provider"]),
        model=row["model"],
        prompt=str(row["prompt"]),
        brief_json=row["brief_json"],
        generation_seed=row["generation_seed"],
        local_path=row["local_path"],
        file_sha256=row["file_sha256"],
        duration_seconds=row["duration_seconds"],
        width=row["width"],
        height=row["height"],
        aspect_ratio=row["aspect_ratio"],
        variant_index=int(row["variant_index"]),
        generated_at=row["generated_at"],
        status=str(row["status"]),
        approved_at=row["approved_at"],
        usage_count=int(row["usage_count"]),
        max_usage=row["max_usage"],
        last_used_at=row["last_used_at"],
        production_asset=bool(row["production_asset"]),
        reject_reason=row["reject_reason"],
        generation_job_id=int(row["generation_job_id"])
        if "generation_job_id" in keys and row["generation_job_id"] is not None
        else None,
        source_media_id=int(row["source_media_id"])
        if "source_media_id" in keys and row["source_media_id"] is not None
        else None,
    )


def row_to_reference(row: Any) -> ReferenceVideo:
    keys = row.keys() if hasattr(row, "keys") else []
    return ReferenceVideo(
        id=int(row["id"]) if "id" in keys and row["id"] is not None else None,
        platform=row["platform"],
        external_id=row["external_id"],
        url=row["url"],
        title=row["title"],
        channel=row["channel"],
        channel_id=row["channel_id"],
        description=row["description"],
        duration_sec=row["duration_sec"],
        view_count=row["view_count"],
        like_count=row["like_count"],
        comment_count=row["comment_count"],
        published_at=row["published_at"],
        thumbnail_url=row["thumbnail_url"],
        source_query=row["source_query"],
        production_asset=bool(row["production_asset"]),
        virality_score=row["virality_score"] if "virality_score" in keys else None,
        last_refreshed_at=row["last_refreshed_at"] if "last_refreshed_at" in keys else None,
    )
