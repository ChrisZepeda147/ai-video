-- Viral discovery reference catalog (REFERENCES ONLY — never production assets).
-- Runtime database: data/discovery/catalog.sqlite

CREATE TABLE IF NOT EXISTS reference_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    channel TEXT,
    channel_id TEXT,
    description TEXT,
    duration_sec REAL,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    thumbnail_url TEXT,
    source_query TEXT,
    production_asset INTEGER NOT NULL DEFAULT 0 CHECK (production_asset = 0),
    UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_reference_videos_platform
    ON reference_videos (platform);

CREATE INDEX IF NOT EXISTS idx_reference_videos_last_seen
    ON reference_videos (last_seen_at);

CREATE INDEX IF NOT EXISTS idx_reference_videos_discovered
    ON reference_videos (discovered_at);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    platform TEXT NOT NULL,
    source_query TEXT,
    search_limit INTEGER,
    ids_found INTEGER NOT NULL DEFAULT 0,
    ids_new INTEGER NOT NULL DEFAULT 0,
    ids_updated INTEGER NOT NULL DEFAULT 0,
    ids_skipped_cooldown INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_started
    ON discovery_runs (started_at);

-- Extended columns on reference_videos / discovery_runs are applied via store migrations
-- for existing databases created before this schema version.

CREATE TABLE IF NOT EXISTS reference_metrics (
    reference_id INTEGER PRIMARY KEY,
    virality_score REAL NOT NULL DEFAULT 0,
    age_hours REAL,
    age_days REAL,
    views_per_day REAL,
    views_per_hour REAL,
    like_ratio REAL,
    comment_ratio REAL,
    velocity_component REAL,
    recency_component REAL,
    engagement_component REAL,
    view_count_snapshot INTEGER,
    like_count_snapshot INTEGER,
    comment_count_snapshot INTEGER,
    scored_at TEXT NOT NULL,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reference_metrics_score
    ON reference_metrics (virality_score DESC);

CREATE TABLE IF NOT EXISTS reference_niches (
    reference_id INTEGER NOT NULL,
    niche TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    assigned_at TEXT NOT NULL,
    assignment_source TEXT NOT NULL,
    PRIMARY KEY (reference_id, niche),
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reference_niches_niche
    ON reference_niches (niche, relevance_score DESC);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'youtube',
    query_normalized TEXT NOT NULL,
    niche TEXT,
    searched_at TEXT NOT NULL,
    run_id INTEGER,
    results_count INTEGER NOT NULL DEFAULT 0,
    ids_new INTEGER NOT NULL DEFAULT 0,
    ids_existing INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES discovery_runs (id)
);

CREATE INDEX IF NOT EXISTS idx_search_history_query
    ON search_history (platform, query_normalized, searched_at DESC);

CREATE TABLE IF NOT EXISTS reference_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    analyzed_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    analysis_version TEXT NOT NULL,
    genre TEXT,
    hook_type TEXT,
    emotional_trigger TEXT,
    pacing_style TEXT,
    tension_structure TEXT,
    story_structure TEXT,
    setting_type TEXT,
    visual_mood TEXT,
    visual_energy TEXT,
    camera_style TEXT,
    lighting_style TEXT,
    subject_type TEXT,
    ending_style TEXT,
    transferable_patterns TEXT,
    avoid_copying TEXT,
    analysis_json TEXT NOT NULL,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reference_analyses_ref
    ON reference_analyses (reference_id, analyzed_at DESC);

CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    analysis_id INTEGER NOT NULL,
    niche TEXT,
    title TEXT NOT NULL,
    hook_idea TEXT,
    visual_premise TEXT,
    setting TEXT,
    subject TEXT,
    camera_movement TEXT,
    mood TEXT,
    story_premise TEXT,
    variation_family TEXT,
    originality_notes TEXT,
    status TEXT NOT NULL DEFAULT 'generated',
    production_asset INTEGER NOT NULL DEFAULT 0 CHECK (production_asset = 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_id) REFERENCES reference_analyses (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_concepts_reference
    ON concepts (reference_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_concepts_niche
    ON concepts (niche, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_concepts_variation
    ON concepts (reference_id, variation_family);

-- Source media: actual audio/video/topic used for production (NOT auto production assets).
CREATE TABLE IF NOT EXISTS source_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER,
    platform TEXT,
    external_id TEXT,
    url TEXT,
    title TEXT NOT NULL,
    media_type TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    local_path TEXT,
    transcript TEXT,
    transcript_hash TEXT,
    duration_sec REAL,
    rights_confidence REAL,
    monetization_confidence REAL,
    reuse_confidence REAL,
    seen_as_reference INTEGER NOT NULL DEFAULT 0,
    actually_used_in_content INTEGER NOT NULL DEFAULT 0,
    reuse_explanations_json TEXT,
    risk_explanations_json TEXT,
    production_asset INTEGER NOT NULL DEFAULT 0 CHECK (production_asset = 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_source_media_reference
    ON source_media (reference_id);

CREATE INDEX IF NOT EXISTS idx_source_media_transcript_hash
    ON source_media (transcript_hash);

CREATE TABLE IF NOT EXISTS source_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_media_id INTEGER NOT NULL,
    start_sec REAL,
    end_sec REAL,
    transcript TEXT,
    local_path TEXT,
    rights_confidence REAL,
    monetization_confidence REAL,
    reuse_confidence REAL,
    FOREIGN KEY (source_media_id) REFERENCES source_media (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_segments_media
    ON source_segments (source_media_id);

-- Cursor handoff jobs for AI image/video generation.
CREATE TABLE IF NOT EXISTS generation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    origin_type TEXT NOT NULL,
    reference_id INTEGER,
    concept_id INTEGER,
    source_media_id INTEGER,
    image_count INTEGER NOT NULL DEFAULT 0,
    video_count INTEGER NOT NULL DEFAULT 0,
    style TEXT,
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    niche TEXT,
    prompt_summary TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    job_json_path TEXT,
    cursor_prompt_path TEXT,
    output_dir TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    imported_at TEXT,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE SET NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE SET NULL,
    FOREIGN KEY (source_media_id) REFERENCES source_media (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_status
    ON generation_jobs (status, created_at DESC);

-- Finished Short assembly projects.
CREATE TABLE IF NOT EXISTS production_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    niche TEXT,
    origin_type TEXT DEFAULT 'reference',
    reference_id INTEGER,
    source_media_id INTEGER,
    source_segment_id INTEGER,
    concept_id INTEGER,
    format_profile TEXT NOT NULL DEFAULT 'audio_visuals',
    duration_sec REAL,
    status TEXT NOT NULL DEFAULT 'draft',
    output_path TEXT,
    timeline_json TEXT,
    hook_text TEXT,
    caption_preset TEXT DEFAULT 'viral_bold',
    error_message TEXT,
    monetization_confidence REAL,
    rights_confidence REAL,
    reuse_confidence REAL,
    risk_explanations_json TEXT,
    created_at TEXT NOT NULL,
    rendered_at TEXT,
    FOREIGN KEY (source_media_id) REFERENCES source_media (id) ON DELETE SET NULL,
    FOREIGN KEY (source_segment_id) REFERENCES source_segments (id) ON DELETE SET NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_production_projects_status
    ON production_projects (status, created_at DESC);

CREATE TABLE IF NOT EXISTS production_project_visuals (
    project_id INTEGER NOT NULL,
    visual_asset_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, visual_asset_id),
    FOREIGN KEY (project_id) REFERENCES production_projects (id) ON DELETE CASCADE,
    FOREIGN KEY (visual_asset_id) REFERENCES visual_assets (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS visual_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id INTEGER,
    reference_id INTEGER,
    generation_job_id INTEGER,
    source_media_id INTEGER,
    niche TEXT,
    variation_family TEXT,
    asset_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    prompt TEXT NOT NULL,
    brief_json TEXT,
    generation_seed TEXT,
    local_path TEXT,
    file_sha256 TEXT,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    aspect_ratio TEXT,
    variant_index INTEGER NOT NULL DEFAULT 1,
    generated_at TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    approved_at TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    max_usage INTEGER,
    last_used_at TEXT,
    production_asset INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE SET NULL,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE SET NULL,
    FOREIGN KEY (generation_job_id) REFERENCES generation_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY (source_media_id) REFERENCES source_media (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_visual_assets_concept
    ON visual_assets (concept_id, variant_index);

CREATE INDEX IF NOT EXISTS idx_visual_assets_status
    ON visual_assets (status, niche);

CREATE INDEX IF NOT EXISTS idx_visual_assets_reference
    ON visual_assets (reference_id, status);

CREATE INDEX IF NOT EXISTS idx_visual_assets_family
    ON visual_assets (variation_family, status);

CREATE INDEX IF NOT EXISTS idx_visual_assets_sha
    ON visual_assets (file_sha256);

-- Connected social publishing accounts (tokens stored outside git).
CREATE TABLE IF NOT EXISTS publishing_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    display_name TEXT NOT NULL,
    platform_account_id TEXT,
    username TEXT,
    niche TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    auth_status TEXT NOT NULL DEFAULT 'disconnected',
    token_expires_at TEXT,
    capabilities_json TEXT,
    posting_available INTEGER NOT NULL DEFAULT 0,
    audit_note TEXT,
    credentials_ref TEXT,
    created_at TEXT NOT NULL,
    last_verified_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_publishing_accounts_platform
    ON publishing_accounts (platform, enabled);

CREATE TABLE IF NOT EXISTS publishing_account_defaults (
    niche TEXT PRIMARY KEY,
    youtube_account_id INTEGER,
    tiktok_account_id INTEGER,
    instagram_account_id INTEGER,
    FOREIGN KEY (youtube_account_id) REFERENCES publishing_accounts (id) ON DELETE SET NULL,
    FOREIGN KEY (tiktok_account_id) REFERENCES publishing_accounts (id) ON DELETE SET NULL,
    FOREIGN KEY (instagram_account_id) REFERENCES publishing_accounts (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS publishing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_project_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    title TEXT,
    caption TEXT,
    hashtags TEXT,
    metadata_json TEXT,
    scheduled_at TEXT,
    timezone TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    platform_post_id TEXT,
    platform_url TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    published_at TEXT,
    FOREIGN KEY (production_project_id) REFERENCES production_projects (id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES publishing_accounts (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_publishing_jobs_status
    ON publishing_jobs (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_publishing_jobs_project
    ON publishing_jobs (production_project_id, account_id);

-- Analytics: creative attributes per published post (derived once).
CREATE TABLE IF NOT EXISTS analytics_post_features (
    publishing_job_id INTEGER PRIMARY KEY,
    production_project_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    niche TEXT,
    features_json TEXT NOT NULL,
    hook_formula TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (publishing_job_id) REFERENCES publishing_jobs (id) ON DELETE CASCADE,
    FOREIGN KEY (production_project_id) REFERENCES production_projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analytics_features_niche
    ON analytics_post_features (niche, hook_formula);

-- Analytics: historical metric snapshots (never overwrite).
CREATE TABLE IF NOT EXISTS analytics_post_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publishing_job_id INTEGER NOT NULL,
    production_project_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    platform_post_id TEXT,
    snapshot_at TEXT NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    watch_time_sec REAL,
    avg_watch_duration_sec REAL,
    completion_rate REAL,
    retention REAL,
    followers_gained INTEGER,
    impressions INTEGER,
    click_through_rate REAL,
    revenue REAL,
    raw_json TEXT,
    performance_score REAL,
    performance_tier TEXT,
    views_vs_account_median REAL,
    velocity_views_per_day REAL,
    FOREIGN KEY (publishing_job_id) REFERENCES publishing_jobs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_job
    ON analytics_post_snapshots (publishing_job_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_account
    ON analytics_post_snapshots (account_id, snapshot_at DESC);

-- Data-informed winner summaries per niche/account.
CREATE TABLE IF NOT EXISTS performance_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    account_id INTEGER,
    profile_json TEXT NOT NULL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (niche, account_id),
    FOREIGN KEY (account_id) REFERENCES publishing_accounts (id) ON DELETE SET NULL
);

-- Pilot batches: orchestrated first-run / experiment workflows.
CREATE TABLE IF NOT EXISTS pilot_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    niche TEXT,
    account_id INTEGER,
    batch_size INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'planning',
    config_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    FOREIGN KEY (account_id) REFERENCES publishing_accounts (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pilot_batches_status
    ON pilot_batches (status, created_at DESC);

CREATE TABLE IF NOT EXISTS pilot_batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    slot_label TEXT,
    strategy TEXT NOT NULL,
    format_profile TEXT,
    reference_id INTEGER,
    source_media_id INTEGER,
    concept_id INTEGER,
    generation_job_id INTEGER,
    production_project_id INTEGER,
    publishing_job_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    stages_json TEXT NOT NULL DEFAULT '{}',
    error_stage TEXT,
    error_message TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES pilot_batches (id) ON DELETE CASCADE,
    FOREIGN KEY (reference_id) REFERENCES reference_videos (id) ON DELETE SET NULL,
    FOREIGN KEY (source_media_id) REFERENCES source_media (id) ON DELETE SET NULL,
    FOREIGN KEY (generation_job_id) REFERENCES generation_jobs (id) ON DELETE SET NULL,
    FOREIGN KEY (production_project_id) REFERENCES production_projects (id) ON DELETE SET NULL,
    FOREIGN KEY (publishing_job_id) REFERENCES publishing_jobs (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pilot_items_batch
    ON pilot_batch_items (batch_id, sort_order);

-- Production content library (NOT discovery references — never write discovery IDs to content/used.json).
CREATE TABLE IF NOT EXISTS production_library_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_key TEXT NOT NULL UNIQUE,
    slug TEXT,
    title TEXT NOT NULL,
    internal_name TEXT,
    speaker TEXT,
    podcast_source TEXT,
    source_url TEXT,
    source_platform TEXT,
    source_external_id TEXT,
    source_start_sec REAL,
    source_end_sec REAL,
    transcript_segment TEXT,
    transcript_hash TEXT,
    topic TEXT,
    hook TEXT,
    tags_json TEXT,
    scene_plan_json TEXT,
    creation_prompt TEXT,
    creation_command_job_id INTEGER,
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    parent_video_id INTEGER,
    version_label TEXT,
    change_summary TEXT,
    posted INTEGER NOT NULL DEFAULT 0,
    platform_ids_json TEXT,
    thumbnail_path TEXT,
    final_output_path TEXT,
    duration_sec REAL,
    production_project_id INTEGER,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (parent_video_id) REFERENCES production_library_videos (id) ON DELETE SET NULL,
    FOREIGN KEY (production_project_id) REFERENCES production_projects (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_production_library_speaker
    ON production_library_videos (speaker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_production_library_source
    ON production_library_videos (source_platform, source_external_id);

CREATE INDEX IF NOT EXISTS idx_production_library_transcript_hash
    ON production_library_videos (transcript_hash);

CREATE INDEX IF NOT EXISTS idx_production_library_parent
    ON production_library_videos (parent_video_id, version);

CREATE TABLE IF NOT EXISTS production_video_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    component_type TEXT NOT NULL,
    label TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    local_path TEXT,
    url TEXT,
    text_content TEXT,
    start_sec REAL,
    end_sec REAL,
    metadata_json TEXT,
    file_sha256 TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES production_library_videos (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_production_components_video
    ON production_video_components (video_id, component_type, sort_order);

-- Reusable visual packs derived from existing clip folders / broll_ids (no duplicate media).
CREATE TABLE IF NOT EXISTS production_visual_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_key TEXT NOT NULL UNIQUE,
    display_id TEXT,
    category TEXT NOT NULL DEFAULT 'Custom',
    label TEXT NOT NULL,
    clips_root_path TEXT,
    broll_ids_json TEXT,
    preview_clip_path TEXT,
    source_video_id INTEGER,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_video_id) REFERENCES production_library_videos (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_visual_packs_category
    ON production_visual_packs (category, label);

-- Exact audio + visual pairing usage per owner (Chris / Stephen).
CREATE TABLE IF NOT EXISTS production_combination_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    audio_component_id INTEGER NOT NULL,
    visual_pack_id INTEGER NOT NULL,
    rendered_video_id INTEGER,
    audio_start_sec REAL,
    audio_end_sec REAL,
    visual_start_sec REAL,
    visual_end_sec REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (audio_component_id) REFERENCES production_video_components (id) ON DELETE CASCADE,
    FOREIGN KEY (visual_pack_id) REFERENCES production_visual_packs (id) ON DELETE CASCADE,
    FOREIGN KEY (rendered_video_id) REFERENCES production_library_videos (id) ON DELETE SET NULL,
    UNIQUE (owner, audio_component_id, visual_pack_id)
);

CREATE INDEX IF NOT EXISTS idx_combination_usage_owner_audio
    ON production_combination_usage (owner, audio_component_id);

CREATE INDEX IF NOT EXISTS idx_combination_usage_pack
    ON production_combination_usage (visual_pack_id, owner);

-- User corrections: YouTube source id -> canonical speaker (remembered across jobs).
CREATE TABLE IF NOT EXISTS production_speaker_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_external_id TEXT NOT NULL UNIQUE,
    speaker TEXT NOT NULL,
    source_url TEXT,
    speech_title TEXT,
    corrected_by TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_speaker_corrections_speaker
    ON production_speaker_corrections (speaker);

-- Website natural-language commands handed to Cursor Agent CLI.
CREATE TABLE IF NOT EXISTS cursor_command_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    user_command TEXT NOT NULL,
    enriched_prompt TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    cursor_session_id TEXT,
    cursor_request_id TEXT,
    production_video_id INTEGER,
    parent_video_id INTEGER,
    production_project_id INTEGER,
    stdout_log TEXT,
    stderr_log TEXT,
    agent_messages_json TEXT,
    agent_result TEXT,
    error_message TEXT,
    error_summary TEXT,
    final_output_path TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (production_video_id) REFERENCES production_library_videos (id) ON DELETE SET NULL,
    FOREIGN KEY (parent_video_id) REFERENCES production_library_videos (id) ON DELETE SET NULL,
    FOREIGN KEY (production_project_id) REFERENCES production_projects (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_cursor_command_jobs_status
    ON cursor_command_jobs (status, created_at DESC);

-- Weekly 7am automation (Sunday feed, 3 videos/day per owner).
CREATE TABLE IF NOT EXISTS weekly_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT 'chris',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (week_start, owner)
);

CREATE TABLE IF NOT EXISTS weekly_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES weekly_plans (id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    slot INTEGER NOT NULL,
    speaker TEXT NOT NULL DEFAULT '',
    visual_direction TEXT NOT NULL DEFAULT '',
    image_paths TEXT NOT NULL DEFAULT '[]',
    image_prompt TEXT NOT NULL DEFAULT '',
    require_stills_first INTEGER NOT NULL DEFAULT 0,
    brief_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    job_key TEXT,
    video_id INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (plan_id, day, slot)
);

CREATE INDEX IF NOT EXISTS idx_weekly_slots_status ON weekly_slots (status);
