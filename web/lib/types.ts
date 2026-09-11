export type NicheTag = {
  niche: string;
  relevance_score: number;
  assignment_source: string;
};

export type ReferenceMetrics = {
  virality_score?: number | null;
  age_hours?: number | null;
  age_days?: number | null;
  views_per_day?: number | null;
  views_per_hour?: number | null;
  like_ratio?: number | null;
  comment_ratio?: number | null;
};

export type ReferenceItem = {
  id: number;
  platform: string;
  external_id: string;
  title: string;
  channel?: string | null;
  url: string;
  thumbnail_url?: string | null;
  published_at?: string | null;
  age_label?: string | null;
  view_count?: number | null;
  like_count?: number | null;
  comment_count?: number | null;
  virality_score?: number | null;
  internal_fit_score?: number | null;
  internal_fit_note?: string | null;
  niches: NicheTag[];
  production_asset: boolean;
  has_analysis: boolean;
  analysis_count: number;
  concepts_generated: number;
  concepts_approved: number;
  exhausted: boolean;
  metrics?: ReferenceMetrics | null;
};

export type ReferencesResponse = {
  items: ReferenceItem[];
  count: number;
};

export type NicheCoverageItem = {
  niche: string;
  reference_count: number;
  enabled: boolean;
};

export type DiscoveryStats = {
  total_references: number;
  references_added_today: number;
  high_virality_references: number;
  searches_today: number;
  detail_requests_today: number;
  discovery_runs: number;
  production_assets: number;
  concepts_ready: number;
  visuals_waiting_review: number;
  niche_coverage: NicheCoverageItem[];
};

export type NichesResponse = {
  items: NicheCoverageItem[];
};

export type ScanResponse = {
  query: string;
  ids_found: number;
  ids_new: number;
  ids_updated: number;
  ids_existing: number;
  ids_skipped_refresh: number;
  detail_requests: number;
  searches_executed: number;
  searches_skipped: number;
  skipped_cooldown: boolean;
};

export type DiscoverRunResponse = {
  searches_executed: number;
  searches_skipped_cooldown: number;
  searches_skipped_limit: number;
  searches_skipped_niche_cap: number;
  ids_new: number;
  ids_updated: number;
  ids_existing: number;
  detail_requests: number;
  skipped_terms: string[];
};

export type AnalysisItem = {
  id: number;
  reference_id: number;
  analyzed_at: string;
  provider: string;
  model?: string | null;
  analysis_version: string;
  observed: Record<string, unknown>;
  inferred: Record<string, unknown>;
  hook_type?: string | null;
  emotional_trigger?: string | null;
  pacing_style?: string | null;
  story_structure?: string | null;
  visual_mood?: string | null;
  transferable_patterns: string;
  avoid_copying: string;
  analysis_json: Record<string, unknown>;
  cached?: boolean;
};

export type AnalysisResponse = {
  item: AnalysisItem | null;
  items: AnalysisItem[];
};

export type ConceptItem = {
  id: number;
  reference_id: number;
  reference_title?: string | null;
  reference_virality_score?: number | null;
  analysis_id: number;
  niche?: string | null;
  title: string;
  hook_idea?: string | null;
  visual_premise?: string | null;
  setting?: string | null;
  subject?: string | null;
  camera_movement?: string | null;
  mood?: string | null;
  story_premise?: string | null;
  variation_family?: string | null;
  originality_notes?: string | null;
  status: string;
  production_asset: boolean;
  created_at: string;
};

export type ConceptsResponse = {
  items: ConceptItem[];
  count: number;
};

export type GenerateConceptsResponse = {
  reference_id: number;
  requested: number;
  stored: number;
  rejected_similar: number;
  skipped_exhaustion: number;
  concepts: ConceptItem[];
};

export type ConceptStatusResponse = {
  updated: number[];
  count: number;
};

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: "offline" | "http" | "malformed"; message: string; status?: number };

export type RiskScoresItem = {
  monetization_confidence: number;
  rights_confidence: number;
  reuse_confidence: number;
  monetization_level: string;
  rights_level: string;
  reuse_level: string;
  explanations: Record<string, string[]>;
};

export type SourceMediaItem = {
  id: number;
  title: string;
  source_mode: string;
  media_type: string;
  reference_id?: number | null;
  download_status?: string | null;
  download_path?: string | null;
  local_path?: string | null;
  transcript?: string | null;
  reuse_confidence?: number | null;
  rights_confidence?: number | null;
  monetization_confidence?: number | null;
  risk_scores?: RiskScoresItem | null;
};

export type SourceMediaResponse = {
  item: SourceMediaItem;
  reuse_report: Record<string, unknown>;
  risk_scores: RiskScoresItem;
};

export type GenerationJobItem = {
  id: number;
  job_key: string;
  origin_type: string;
  status: string;
  image_count: number;
  video_count: number;
  style?: string | null;
  aspect_ratio: string;
  prompt_summary?: string | null;
  reference_id?: number | null;
  concept_id?: number | null;
  source_media_id?: number | null;
  output_dir?: string | null;
  cursor_prompt_path?: string | null;
  created_at: string;
};

export type GenerationJobsResponse = {
  items: GenerationJobItem[];
  count: number;
};

export type VisualAssetItem = {
  id: number;
  asset_type: string;
  status: string;
  prompt: string;
  niche?: string | null;
  media_url?: string | null;
  production_asset: boolean;
  reject_reason?: string | null;
};

export type VisualsReviewResponse = {
  items: VisualAssetItem[];
  count: number;
};

export type WorkbenchCandidateItem = {
  reference_id?: number | null;
  title: string;
  url: string;
  transcript_snippet: string;
  virality_score?: number | null;
  reuse_confidence: number;
  rights_confidence: number;
  monetization_confidence: number;
  explanations: string[];
};

export type WorkbenchFindResponse = {
  items: WorkbenchCandidateItem[];
  count: number;
};

export type ProductionProjectItem = {
  id: number;
  slug: string;
  title: string;
  format_profile: string;
  origin_type?: string | null;
  status: string;
  niche?: string | null;
  source_media_id?: number | null;
  duration_sec?: number | null;
  output_path?: string | null;
  timeline_json?: string | null;
  hook_text?: string | null;
  caption_preset?: string | null;
  monetization_confidence?: number | null;
  rights_confidence?: number | null;
  reuse_confidence?: number | null;
  created_at: string;
  rendered_at?: string | null;
  error_message?: string | null;
};

export type ProductionProjectsResponse = {
  items: ProductionProjectItem[];
  count: number;
};

export type VideoLibraryItem = {
  key: string;
  source: "production" | "legacy" | "library";
  project_id?: number | null;
  library_id?: number | null;
  legacy_id?: string | null;
  slug: string;
  title: string;
  format_profile: string;
  origin_type?: string | null;
  status: string;
  niche?: string | null;
  output_path?: string | null;
  output_paths: string[];
  preview_available: boolean;
  missing_paths: string[];
  media_kind?: import("@/lib/format").VideoMediaKind | "other";
  speaker?: string | null;
  display_path?: string | null;
  editable?: boolean;
  duration_sec?: number | null;
  created_at?: string | null;
  rendered_at?: string | null;
  youtube_id?: string | null;
  monetization_confidence?: number | null;
  rights_confidence?: number | null;
  reuse_confidence?: number | null;
  error_message?: string | null;
  published_to?: VideoPublishedLink[];
};

export type VideoPublishedLink = {
  job_id: number;
  account_id: number;
  platform: string;
  platform_url?: string | null;
  platform_post_id?: string | null;
  published_at?: string | null;
  account_display_name?: string | null;
  account_owner?: string | null;
  account_username?: string | null;
};

export type VideoLibraryResponse = {
  items: VideoLibraryItem[];
  count: number;
  summary: {
    total: number;
    production: number;
    library?: number;
    legacy: number;
    audio?: number;
    video?: number;
    video_audio?: number;
    preview_ready: number;
    missing_files: number;
  };
};

export type ShortBuildVisualStyle = {
  id: string;
  label: string;
  query?: string;
};

export type ShortPoolAsset = {
  youtube_id: string;
  title: string;
  url?: string;
  query?: string;
  kind?: string;
  local_path?: string;
  duration_sec?: number | null;
  use_count?: number;
  available?: boolean;
};

export type ShortPoolResponse = {
  summary: {
    speech_count: number;
    broll_count: number;
    combinations_used: number;
    updated_at?: string;
  };
  speech: ShortPoolAsset[];
  broll: ShortPoolAsset[];
  combinations: Array<{
    key?: string;
    speech_youtube_id: string;
    broll_youtube_ids: string[];
    slug: string;
    created_at: string;
  }>;
};

export type ShortBuildDefaults = {
  speaker?: string;
  speech_query: string;
  broll_query: string;
  min_seconds: number;
  max_seconds: number;
  segment_length: number;
  visual_styles: ShortBuildVisualStyle[];
  config_path?: string;
};

export type ShortBuildJob = {
  job_id: string;
  slug: string;
  status: string;
  visual_style?: string;
  broll_query?: string;
  target_seconds?: number;
  output_path?: string | null;
  preview_url?: string | null;
  poll_url?: string;
  error?: string | null;
  duration_sec?: number | null;
  speech_youtube_id?: string | null;
  broll_youtube_ids?: string[] | null;
};

export type CommandJob = {
  job_key: string;
  job_id?: number;
  status: string;
  user_command: string;
  batch?: boolean;
  batch_count?: number;
  jobs?: CommandJob[];
  cursor_session_id?: string | null;
  production_video_id?: number | null;
  parent_video_id?: number | null;
  agent_result?: string | null;
  stdout_log?: string | null;
  stderr_log?: string | null;
  error_message?: string | null;
  final_output_path?: string | null;
  poll_url?: string;
  cursor_available?: boolean;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type ProductionVideoComponent = {
  id: number;
  video_id: number;
  component_type: string;
  label?: string | null;
  sort_order?: number;
  local_path?: string | null;
  display_path?: string | null;
  preview_available?: boolean;
  media_kind?: "audio" | "video" | "other";
  url?: string | null;
  text_content?: string | null;
  start_sec?: number | null;
  end_sec?: number | null;
};

export type ProductionLibraryVideo = {
  id: number;
  video_key: string;
  slug?: string | null;
  title: string;
  speaker?: string | null;
  podcast_source?: string | null;
  source_url?: string | null;
  topic?: string | null;
  hook?: string | null;
  status: string;
  version?: number;
  parent_video_id?: number | null;
  version_label?: string | null;
  final_output_path?: string | null;
  thumbnail_path?: string | null;
  duration_sec?: number | null;
  created_at: string;
  metadata?: Record<string, unknown> | null;
  components?: ProductionVideoComponent[];
  versions?: Array<{
    id: number;
    video_key: string;
    version?: number;
    version_label?: string | null;
    status?: string;
    final_output_path?: string | null;
    created_at?: string;
  }>;
};

export type CombinationAudioItem = {
  component_id: number;
  video_id: number;
  display_id: string;
  speaker: string;
  label?: string;
  local_path?: string | null;
  display_path?: string | null;
  preview_available?: boolean;
  start_sec?: number | null;
  end_sec?: number | null;
  duration_sec?: number | null;
  source_url?: string | null;
  transcript_excerpt?: string;
  video_title?: string;
};

export type CombinationVisualPack = {
  id: number;
  pack_key?: string;
  display_id?: string | null;
  category: string;
  label: string;
  clips_root_path?: string | null;
  preview_clip_path?: string | null;
  display_path?: string | null;
  preview_available?: boolean;
  clip_count?: number;
  duration_sec?: number | null;
  broll_ids?: string[];
};

export type CombinationCatalog = {
  owners: string[];
  selected_owner?: string | null;
  audio_by_speaker: Record<string, CombinationAudioItem[]>;
  visual_packs: CombinationVisualPack[];
  visual_by_category?: Record<string, CombinationVisualPack[]>;
  audio_count: number;
  visual_pack_count: number;
};

export type CombinationVisualStatus = {
  visual_pack_id: number;
  display_id?: string | null;
  category?: string;
  label?: string;
  preview_clip_path?: string | null;
  clip_count?: number;
  duration_sec?: number | null;
  status: "available" | "used_by_selected_owner" | "used_by_other_owner";
  available: boolean;
  used_by_selected_owner: boolean;
  used_by_other_owner: boolean;
  other_owner?: string | null;
  rendered_video_ids?: number[];
};

export type CombinationStatusResponse = {
  owner: string;
  audio_component_id: number;
  audio: {
    display_id?: string | null;
    speaker?: string | null;
    local_path?: string | null;
    transcript_excerpt?: string;
    duration_sec?: number | null;
    start_sec?: number | null;
    end_sec?: number | null;
    source_url?: string | null;
  };
  visuals: CombinationVisualStatus[];
  advisory_reuse?: {
    prior_usage_detected?: boolean;
    summary?: string;
  };
};

export type SharedSyncGitStatus = {
  branch?: string | null;
  commit?: string | null;
  remote_ref?: string | null;
  remote_commit?: string | null;
  commits_behind?: number | null;
  commits_ahead?: number | null;
  code_sync_hint?: string | null;
};

export type SharedSyncStatus = {
  owner: string;
  packages_on_disk: number;
  imports_recorded: number;
  pending_import?: number;
  exports_recorded: number;
  last_import_at?: string | null;
  last_pull_at?: string | null;
  last_push_at?: string | null;
  last_auto_sync_at?: string | null;
  auto_sync_enabled?: boolean;
  auto_sync_interval_minutes?: number;
  brother_auto_pull_enabled?: boolean;
  brother_auto_pull_interval_minutes?: number;
  last_code_pull_at?: string | null;
  export_enabled: boolean;
  git?: SharedSyncGitStatus;
};

export type SharedSyncPullImportResult = {
  skipped?: boolean;
  reason?: string;
  pull?: Record<string, unknown> | null;
  pull_warning?: string | null;
  git?: SharedSyncGitStatus;
  import?: {
    found: number;
    imported: number;
    skipped: number;
    errors: number;
    items?: Array<Record<string, unknown>>;
  };
  status: SharedSyncStatus;
};

export type CombinationRenderResponse = {
  video: ProductionLibraryVideo;
  usage: Record<string, unknown>;
  output_path: string;
  slug: string;
  owner: string;
};

export type VideoImportResponse = {
  results: Array<{
    slug: string;
    status: string;
    reason?: string;
    project_id?: number;
    output_path?: string;
    title?: string;
    missing_paths?: string[];
  }>;
  count: number;
  imported_count: number;
  ready_count: number;
  skipped_count: number;
  imported: VideoImportResponse["results"];
  skipped: VideoImportResponse["results"];
};

export type PublishingOwner = "stephen" | "chris";

export type PublishingAccountItem = {
  id: number;
  platform: string;
  display_name: string;
  owner?: PublishingOwner | string;
  platform_account_id?: string | null;
  username?: string | null;
  niche?: string | null;
  enabled: boolean;
  auth_status: string;
  posting_available: boolean;
  audit_note?: string | null;
  token_expires_at?: string | null;
  created_at: string;
  last_verified_at?: string | null;
};

export type PublishingAccountsResponse = {
  items: PublishingAccountItem[];
  count: number;
};

export type PublishingJobItem = {
  id: number;
  production_project_id: number;
  account_id: number;
  platform: string;
  title?: string | null;
  caption?: string | null;
  hashtags?: string | null;
  scheduled_at?: string | null;
  timezone?: string | null;
  status: string;
  platform_post_id?: string | null;
  platform_url?: string | null;
  error_message?: string | null;
  attempts: number;
  created_at: string;
  published_at?: string | null;
  account_display_name?: string | null;
};

export type PublishingJobsResponse = {
  items: PublishingJobItem[];
  count: number;
};

export type AnalyticsOverview = {
  total_published_posts: number;
  total_views: number;
  views_last_7_days: number;
  views_last_30_days: number;
  average_performance_score: number | null;
  breakout_count: number;
  underperforming_count: number;
  posts_with_metrics: number;
};

export type AnalyticsPostItem = {
  publishing_job_id: number;
  production_project_id: number;
  account_id: number;
  platform: string;
  title?: string | null;
  platform_url?: string | null;
  published_at?: string | null;
  views?: number | null;
  likes?: number | null;
  comments?: number | null;
  performance_score?: number | null;
  performance_tier?: string | null;
  velocity_views_per_day?: number | null;
  views_vs_account_median?: number | null;
  hook_formula?: string | null;
  niche?: string | null;
  snapshot_at?: string | null;
};

export type AnalyticsPostsResponse = {
  items: AnalyticsPostItem[];
  count: number;
};

export type AnalyticsAccountBoard = {
  account: PublishingAccountItem;
  overview: AnalyticsOverview;
  recent_posts: AnalyticsPostItem[];
  live_metrics?: Record<string, unknown> | null;
};

export type AnalyticsBoardResponse = {
  owner?: string | null;
  accounts: AnalyticsAccountBoard[];
  account_count: number;
};

export type VideoLinkPostResponse = {
  duplicate: boolean;
  job_id: number;
  production_project_id: number;
  platform: string;
  platform_post_id: string;
  platform_url: string;
  account_id: number;
  account_display_name?: string | null;
  account_owner?: string | null;
  refresh?: Record<string, unknown> | null;
};

export type AnalyticsPatternItem = {
  label: string;
  post_count: number;
  avg_performance_score: number;
  avg_views: number;
  breakout_count: number;
};

export type AnalyticsPatternsResponse = {
  items: AnalyticsPatternItem[];
  count: number;
};

export type PreflightCheckItem = {
  label: string;
  status: string;
  detail: string;
  fix_hint?: string | null;
};

export type PublishingSetupPlatform = {
  label: string;
  portal_url: string;
  env_ready: boolean;
  env_keys: string[];
  redirect_uri: string;
  notes: string;
};

export type PublishingSetupResponse = {
  machine_owner: string;
  oauth_redirect_uri: string;
  mock_provider: boolean;
  dry_run: boolean;
  internal_key_configured: boolean;
  target_accounts_per_owner: number;
  owners: string[];
  platforms: Record<string, PublishingSetupPlatform>;
  account_matrix: Record<string, Record<string, { connected: number; total: number; target: number }>>;
  gaps: string[];
  brother_note: string;
};

export type PreflightResponse = {
  summary: {
    ready: number;
    warning: number;
    not_configured: number;
    pilot_ready: boolean;
  };
  groups: Record<string, PreflightCheckItem[]>;
  project_root: string;
};

export type PilotStageItem = {
  status: string;
  message: string;
  entity_id?: number | null;
};

export type PilotBatchItemResponse = {
  id: number;
  batch_id: number;
  sort_order: number;
  slot_label?: string | null;
  strategy: string;
  format_profile?: string | null;
  status: string;
  stages: Record<string, PilotStageItem>;
  error_stage?: string | null;
  error_message?: string | null;
  notes?: string | null;
  reference_id?: number | null;
  source_media_id?: number | null;
  generation_job_id?: number | null;
  production_project_id?: number | null;
  publishing_job_id?: number | null;
};

export type PilotBatchResponse = {
  id: number;
  slug: string;
  name: string;
  niche?: string | null;
  account_id?: number | null;
  batch_size: number;
  status: string;
  created_at: string;
  items: PilotBatchItemResponse[];
};

export type PilotBatchesResponse = {
  items: PilotBatchResponse[];
  count: number;
};

export type ProjectAnalyticsResponse = {
  production_project_id: number;
  features: Record<string, unknown>;
  latest_metrics: Record<string, unknown> | null;
  snapshots: Record<string, unknown>[];
  performance_signals: string[];
  publishing_jobs: PublishingJobItem[];
};
