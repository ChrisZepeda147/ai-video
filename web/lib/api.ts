import type {
  AnalysisResponse,
  ApiResult,
  ConceptStatusResponse,
  ConceptsResponse,
  DiscoverRunResponse,
  DiscoveryStats,
  GenerateConceptsResponse,
  GenerationJobItem,
  GenerationJobsResponse,
  NichesResponse,
  ReferencesResponse,
  ScanResponse,
  SourceMediaResponse,
  VisualsReviewResponse,
  WorkbenchFindResponse,
  ProductionProjectsResponse,
  ProductionProjectItem,
  VideoLibraryResponse,
  VideoImportResponse,
  CommandJob,
  ProductionLibraryVideo,
  ShortBuildDefaults,
  ShortBuildJob,
  ShortPoolResponse,
  PublishingAccountsResponse,
  PublishingJobsResponse,
  AnalyticsOverview,
  AnalyticsPostsResponse,
  AnalyticsPatternsResponse,
  ProjectAnalyticsResponse,
  PreflightResponse,
  PilotBatchesResponse,
  PilotBatchResponse,
} from "@/lib/types";

const DEFAULT_API_URL = "http://127.0.0.1:8000";
const API_FETCH_TIMEOUT_MS = 5000;
const HEALTH_FETCH_TIMEOUT_MS = 12_000;

export function getApiBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (fromEnv) return fromEnv;
  if (typeof window !== "undefined") {
    return `${window.location.origin}/discovery-api`;
  }
  return DEFAULT_API_URL;
}

function internalHeaders(): Record<string, string> {
  const key = process.env.NEXT_PUBLIC_AI_VIDEO_INTERNAL_KEY?.trim();
  return key ? { "X-Internal-Key": key } : {};
}

type QueryValue = string | number | boolean | undefined | null;

function buildUrl(path: string, params?: Record<string, QueryValue>): string {
  const url = new URL(path, getApiBaseUrl());
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
      return String(item);
    });
    return parts.filter(Boolean).join("; ");
  }
  if (detail && typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    if (typeof obj.message === "string") {
      const unrelated = Array.isArray(obj.unrelated) ? obj.unrelated.filter(Boolean) : [];
      if (unrelated.length) {
        return `${obj.message} (${unrelated.join(", ")})`;
      }
      return obj.message;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return "Request failed";
    }
  }
  return "";
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(url, {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(API_FETCH_TIMEOUT_MS),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
    if (!response.ok) {
      let message = `Discovery backend returned ${response.status}`;
      try {
        const err = (await response.json()) as { detail?: unknown };
        const formatted = formatApiErrorDetail(err.detail);
        if (formatted) message = formatted;
      } catch {
        /* ignore */
      }
      if (response.status >= 500) {
        console.error(`Discovery API ${response.status} ${url}: ${message}`);
      }
      return { ok: false, error: "http", message, status: response.status };
    }
    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch {
    return {
      ok: false,
      error: "offline",
      message:
        "Discovery backend is offline. Run npm run dev:api (keeps running) or npm run dev:web (starts API if needed).",
    };
  }
}

export async function fetchHealth(): Promise<ApiResult<{ status: string }>> {
  const url = buildUrl("/health");
  for (let attempt = 0; attempt < 2; attempt++) {
    const result = await fetchJson<{ status: string }>(url, {
      signal: AbortSignal.timeout(HEALTH_FETCH_TIMEOUT_MS),
    });
    if (result.ok) return result;
    if (result.error !== "offline" || attempt > 0) return result;
    await new Promise((r) => setTimeout(r, 400));
  }
  return {
    ok: false,
    error: "offline",
    message:
      "Discovery backend is offline. Run npm run dev:api (keeps running) or npm run dev:web (starts API if needed).",
  };
}

export async function fetchDiscoveryStats(): Promise<ApiResult<DiscoveryStats>> {
  return fetchJson<DiscoveryStats>(buildUrl("/api/discovery/stats"));
}

export async function fetchDiscoveryReferences(params?: {
  niche?: string;
  min_score?: number;
  limit?: number;
  search?: string;
  status?: string;
}): Promise<ApiResult<ReferencesResponse>> {
  return fetchJson<ReferencesResponse>(
    buildUrl("/api/discovery/references", params),
  );
}

export async function fetchDiscoveryTop(params?: {
  niche?: string;
  min_score?: number;
  limit?: number;
}): Promise<ApiResult<ReferencesResponse>> {
  return fetchJson<ReferencesResponse>(buildUrl("/api/discovery/top", params));
}

export async function fetchDiscoveryNiches(): Promise<ApiResult<NichesResponse>> {
  return fetchJson<NichesResponse>(buildUrl("/api/discovery/niches"));
}

export async function postDiscoveryScan(body: {
  query: string;
  niche?: string;
  limit?: number;
  force?: boolean;
}): Promise<ApiResult<ScanResponse>> {
  return fetchJson<ScanResponse>(buildUrl("/api/discovery/scan"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postDiscoveryDiscover(body: {
  max_searches?: number;
  force?: boolean;
}): Promise<ApiResult<DiscoverRunResponse>> {
  return fetchJson<DiscoverRunResponse>(buildUrl("/api/discovery/discover"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchReferenceAnalysis(
  referenceId: number,
): Promise<ApiResult<AnalysisResponse>> {
  return fetchJson<AnalysisResponse>(
    buildUrl(`/api/discovery/references/${referenceId}/analysis`),
  );
}

export async function postAnalyzeReference(
  referenceId: number,
  reanalyze = false,
): Promise<ApiResult<AnalysisResponse>> {
  return fetchJson<AnalysisResponse>(
    buildUrl(`/api/discovery/references/${referenceId}/analyze`),
    { method: "POST", body: JSON.stringify({ reanalyze }) },
  );
}

export async function postGenerateConcepts(
  referenceId: number,
  body: { count: number; niche?: string },
): Promise<ApiResult<GenerateConceptsResponse>> {
  return fetchJson<GenerateConceptsResponse>(
    buildUrl(`/api/discovery/references/${referenceId}/concepts`),
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function fetchConcepts(params?: {
  reference_id?: number;
  niche?: string;
  status?: string;
  limit?: number;
}): Promise<ApiResult<ConceptsResponse>> {
  return fetchJson<ConceptsResponse>(buildUrl("/api/discovery/concepts", params));
}

export async function postShortlistConcepts(
  conceptIds: number[],
): Promise<ApiResult<ConceptStatusResponse>> {
  return fetchJson<ConceptStatusResponse>(buildUrl("/api/discovery/concepts/shortlist"), {
    method: "POST",
    body: JSON.stringify({ concept_ids: conceptIds }),
  });
}

export async function postApproveConcepts(
  conceptIds: number[],
): Promise<ApiResult<ConceptStatusResponse>> {
  return fetchJson<ConceptStatusResponse>(buildUrl("/api/discovery/concepts/approve"), {
    method: "POST",
    body: JSON.stringify({ concept_ids: conceptIds }),
  });
}

export async function postRejectConcepts(
  conceptIds: number[],
): Promise<ApiResult<ConceptStatusResponse>> {
  return fetchJson<ConceptStatusResponse>(buildUrl("/api/discovery/concepts/reject"), {
    method: "POST",
    body: JSON.stringify({ concept_ids: conceptIds }),
  });
}

export async function postCreateSourceMedia(body: {
  source_mode: string;
  reference_id?: number;
  title?: string;
  media_type?: string;
}): Promise<ApiResult<SourceMediaResponse>> {
  return fetchJson<SourceMediaResponse>(buildUrl("/api/source-media"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postCreateGenerationJob(body: {
  origin_type?: string;
  prompt_summary: string;
  image_count: number;
  video_count: number;
  style?: string;
  niche?: string;
  reference_id?: number;
  concept_id?: number;
  source_media_id?: number;
}): Promise<ApiResult<GenerationJobItem>> {
  return fetchJson<GenerationJobItem>(buildUrl("/api/generation/jobs"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchGenerationJobs(params?: {
  status?: string;
  limit?: number;
}): Promise<ApiResult<GenerationJobsResponse>> {
  return fetchJson<GenerationJobsResponse>(buildUrl("/api/generation/jobs", params));
}

export async function postImportGenerationJob(
  jobId: number,
): Promise<ApiResult<{ job_id: number; imported: number; skipped: number; failed: string[] }>> {
  return fetchJson(buildUrl(`/api/generation/jobs/${jobId}/import`), { method: "POST", body: "{}" });
}

export async function fetchVisualsReview(params?: {
  asset_type?: string;
}): Promise<ApiResult<VisualsReviewResponse>> {
  return fetchJson<VisualsReviewResponse>(buildUrl("/api/visuals/review", params));
}

export async function postApproveVisuals(
  assetIds: number[],
): Promise<ApiResult<{ updated: number[]; count: number }>> {
  return fetchJson(buildUrl("/api/visuals/approve"), {
    method: "POST",
    body: JSON.stringify({ asset_ids: assetIds }),
  });
}

export async function postRejectVisuals(
  assetIds: number[],
): Promise<ApiResult<{ updated: number[]; count: number }>> {
  return fetchJson(buildUrl("/api/visuals/reject"), {
    method: "POST",
    body: JSON.stringify({ asset_ids: assetIds }),
  });
}

export async function postWorkbenchFindSource(body: {
  query: string;
  limit?: number;
}): Promise<ApiResult<WorkbenchFindResponse>> {
  return fetchJson<WorkbenchFindResponse>(buildUrl("/api/workbench/find-source"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postWorkbenchCreateOriginal(body: {
  query: string;
  image_count?: number;
  video_count?: number;
  style?: string;
}): Promise<ApiResult<GenerationJobItem>> {
  return fetchJson<GenerationJobItem>(buildUrl("/api/workbench/create-original"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchSourceMedia(sourceMediaId: number) {
  return fetchJson<SourceMediaResponse>(buildUrl(`/api/source-media/${sourceMediaId}`));
}

export async function fetchApprovedVisuals(params?: { limit?: number }) {
  return fetchJson<VisualsReviewResponse>(buildUrl("/api/visuals/approved", params));
}

export async function fetchProductionProject(projectId: number) {
  return fetchJson<ProductionProjectItem>(buildUrl(`/api/production/projects/${projectId}`));
}

export async function postAcquireSource(sourceMediaId: number) {
  return fetchJson(buildUrl(`/api/source-media/${sourceMediaId}/acquire`), { method: "POST", body: "{}" });
}

export async function postClipSegment(sourceMediaId: number, body: { start_sec: number; end_sec: number }) {
  return fetchJson(buildUrl(`/api/source-media/${sourceMediaId}/segments`), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postTranscribeSource(sourceMediaId: number) {
  return fetchJson(buildUrl(`/api/source-media/${sourceMediaId}/transcribe`), { method: "POST", body: "{}" });
}

export async function fetchProductionProjects(params?: { status?: string; limit?: number }) {
  return fetchJson<ProductionProjectsResponse>(buildUrl("/api/production/projects", params));
}

export async function fetchVideoLibrary(params?: { include_missing?: boolean; limit?: number }) {
  return fetchJson<VideoLibraryResponse>(buildUrl("/api/videos/library", params));
}

export async function fetchShortBuildDefaults() {
  return fetchJson<ShortBuildDefaults>(buildUrl("/api/shorts/build/defaults"));
}

export async function fetchShortPool() {
  return fetchJson<ShortPoolResponse>(buildUrl("/api/shorts/pool"));
}

export async function postPullShortPool(body: {
  speech_query: string;
  broll_query?: string;
  visual_style?: string;
  speech_count?: number;
  broll_count?: number;
}) {
  return fetchJson<ShortPoolResponse & { speech_pulled?: number; broll_pulled?: number }>(
    buildUrl("/api/shorts/pool/pull"),
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postBuildShort(body: {
  slug?: string;
  speech_query?: string;
  broll_query?: string;
  speech_url?: string;
  speaker?: string;
  min_seconds?: number;
  max_seconds?: number;
  segment_length?: number;
  apply_grade?: boolean;
  register_site?: boolean;
  rerender?: boolean;
}) {
  return fetchJson<ShortBuildJob>(buildUrl("/api/shorts/build"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchShortBuildStatus(jobId: string) {
  return fetchJson<ShortBuildJob>(buildUrl(`/api/shorts/build/${jobId}`));
}

export async function postImportVideos(body?: {
  slug?: string;
  slugs?: string[];
  rebuild_catalog?: boolean;
  copy_files?: boolean;
}) {
  return fetchJson<VideoImportResponse>(buildUrl("/api/videos/import"), {
    method: "POST",
    body: JSON.stringify(body ?? { rebuild_catalog: true }),
  });
}

export async function postPruneVideoCatalog() {
  return fetchJson<{ legacy_catalog: { removed: number; remaining: number } }>(
    buildUrl("/api/videos/prune"),
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function postUpdateVideoLibraryItem(body: {
  source: "production" | "library" | "legacy";
  library_id?: number;
  project_id?: number;
  legacy_id?: string;
  speaker?: string;
  media_kind?: import("@/lib/format").VideoMediaKind;
  remember_speaker?: boolean;
}) {
  return fetchJson<{ item: import("@/lib/types").VideoLibraryItem }>(
    buildUrl("/api/videos/library/update"),
    {
      method: "POST",
      body: JSON.stringify(body),
      headers: internalHeaders(),
    },
  );
}

export async function postLinkVideoPost(body: {
  account_id: number;
  platform_url: string;
  slug: string;
  title?: string;
  project_id?: number;
  output_path?: string | null;
  niche?: string | null;
  source?: string;
  origin_type?: string;
  format_profile?: string;
  refresh_analytics?: boolean;
}) {
  return fetchJson<import("@/lib/types").VideoLinkPostResponse>(
    buildUrl("/api/videos/library/link-post"),
    {
      method: "POST",
      body: JSON.stringify(body),
      headers: internalHeaders(),
    },
  );
}

export async function fetchPublishingSetup() {
  return fetchJson<import("@/lib/types").PublishingSetupResponse>(buildUrl("/api/config/publishing-setup"));
}

export async function fetchCommandCenter(params?: { owner?: string }) {
  return fetchJson<import("@/lib/types").CommandCenterResponse>(
    buildUrl("/api/command-center", params),
  );
}

export async function fetchPublishingOwner() {
  return fetchJson<{ owner: string }>(buildUrl("/api/config/publishing-owner"));
}

export async function postDeleteVideoLibraryItem(body: {
  source: "production" | "library" | "legacy";
  library_id?: number;
  project_id?: number;
  legacy_id?: string;
  slug?: string;
  delete_files?: boolean;
}) {
  return fetchJson<{ deleted: Record<string, unknown> }>(
    buildUrl("/api/videos/library/delete"),
    {
      method: "POST",
      body: JSON.stringify({ delete_files: true, ...body }),
      headers: internalHeaders(),
      signal: AbortSignal.timeout(60_000),
    },
  );
}

export async function deleteProductionVideo(videoId: number, deleteFiles = true) {
  return fetchJson<{ deleted: Record<string, unknown> }>(
    buildUrl(`/api/library/videos/${videoId}`, { delete_files: deleteFiles }),
    {
      method: "DELETE",
      headers: internalHeaders(),
      signal: AbortSignal.timeout(60_000),
    },
  );
}

export async function postSyncCombinationCatalog(body?: { prune_missing?: boolean }) {
  return fetchJson<{ synced: number; pruned: { removed_audio?: number; removed_visual_packs?: number } }>(
    buildUrl("/api/library/combinations/sync-catalog"),
    { method: "POST", body: JSON.stringify(body ?? { prune_missing: true }) },
  );
}

export async function postCreateProject(body: Record<string, unknown>) {
  return fetchJson<ProductionProjectItem>(buildUrl("/api/production/projects"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postBuildTimeline(projectId: number, body: Record<string, unknown>) {
  return fetchJson(buildUrl(`/api/production/projects/${projectId}/timeline`), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postRenderProject(projectId: number) {
  return fetchJson(buildUrl(`/api/production/projects/${projectId}/render`), { method: "POST", body: "{}" });
}

export async function postApproveProject(projectId: number) {
  return fetchJson(buildUrl(`/api/production/projects/${projectId}/approve`), { method: "POST", body: "{}" });
}

export async function postRejectProject(projectId: number) {
  return fetchJson(buildUrl(`/api/production/projects/${projectId}/reject`), { method: "POST", body: "{}" });
}

export async function postSendProjectToReview(projectId: number) {
  return fetchJson(buildUrl(`/api/production/projects/${projectId}/send-to-review`), { method: "POST", body: "{}" });
}

export async function fetchPublishingAccounts(params?: { platform?: string; owner?: string }) {
  return fetchJson<PublishingAccountsResponse>(buildUrl("/api/accounts", params));
}

export async function postConnectAccount(
  platform: string,
  body: { display_name?: string; niche?: string; owner?: string; redirect_uri?: string },
) {
  return fetchJson<{ auth_url: string; state: string; instructions: string }>(
    buildUrl(`/api/accounts/${platform}/connect`),
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postCompleteAccountConnect(body: { state: string; code: string }) {
  return fetchJson<import("@/lib/types").PublishingAccountItem>(
    buildUrl("/api/accounts/connect/complete"),
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postCreateMockAccount(platform: string, body: { display_name: string; niche?: string }) {
  return fetchJson<import("@/lib/types").PublishingAccountItem>(
    buildUrl(`/api/accounts/mock/${platform}`),
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postDeleteAccount(accountId: number) {
  return fetchJson(buildUrl(`/api/accounts/${accountId}`), { method: "DELETE", body: "{}" });
}

export async function postVerifyAccount(accountId: number) {
  return fetchJson(buildUrl(`/api/accounts/${accountId}/verify`), { method: "POST", body: "{}" });
}

export async function fetchPublishingJobs(params?: { status?: string; production_project_id?: number; limit?: number }) {
  return fetchJson<PublishingJobsResponse>(buildUrl("/api/publishing/jobs", params));
}

export async function postCreatePublishingJobs(body: {
  production_project_id: number;
  account_ids: number[];
  title?: string;
  caption?: string;
  hashtags?: string;
  scheduled_at?: string;
  timezone?: string;
  publish_now?: boolean;
}) {
  return fetchJson<PublishingJobsResponse>(buildUrl("/api/publishing/jobs"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postCancelPublishingJob(jobId: number) {
  return fetchJson(buildUrl(`/api/publishing/jobs/${jobId}/cancel`), { method: "POST", body: "{}" });
}

export async function postRetryPublishingJob(jobId: number) {
  return fetchJson(buildUrl(`/api/publishing/jobs/${jobId}/retry`), { method: "POST", body: "{}" });
}

export function productionMediaUrl(outputPath: string | null | undefined): string | null {
  if (!outputPath) return null;
  const normalized = outputPath.replace(/\\/g, "/");
  const marker = "/downloads/production/";
  const idx = normalized.indexOf(marker);
  if (idx >= 0) {
    return getMediaUrl(normalized.slice(idx + 1));
  }
  return getMediaUrl(normalized);
}

export function getMediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  const normalized = path.replace(/\\/g, "/");
  if (normalized.startsWith("/media/")) {
    return `${getApiBaseUrl()}${normalized}`;
  }
  const rel = normalized.startsWith("/") ? normalized.slice(1) : normalized;
  return `${getApiBaseUrl()}/media/${rel}`;
}

export async function fetchAnalyticsOverview(params?: {
  platform?: string;
  account_id?: number;
  owner?: string;
  niche?: string;
}) {
  return fetchJson<AnalyticsOverview>(buildUrl("/api/analytics/overview", params));
}

export async function fetchAnalyticsBoard(params?: { owner?: string; include_live?: boolean }) {
  return fetchJson<import("@/lib/types").AnalyticsBoardResponse>(
    buildUrl("/api/analytics/board", params),
  );
}

export async function fetchAnalyticsPosts(params?: {
  platform?: string;
  account_id?: number;
  owner?: string;
  niche?: string;
  limit?: number;
}) {
  return fetchJson<AnalyticsPostsResponse>(buildUrl("/api/analytics/posts", params));
}

export async function fetchAnalyticsPatterns(
  kind: "hooks" | "topics" | "formats" | "visuals" | "accounts",
  params?: { niche?: string; limit?: number },
) {
  return fetchJson<AnalyticsPatternsResponse>(buildUrl(`/api/analytics/${kind}`, params));
}

export async function postAnalyticsRefresh(body?: {
  account_id?: number;
  job_id?: number;
  force?: boolean;
  limit?: number;
}) {
  return fetchJson<{ refreshed: number; skipped: number; errors: number }>(
    buildUrl("/api/analytics/refresh"),
    { method: "POST", body: JSON.stringify(body ?? {}) },
  );
}

export async function fetchProjectAnalytics(projectId: number) {
  return fetchJson<ProjectAnalyticsResponse>(buildUrl(`/api/analytics/projects/${projectId}`));
}

export async function fetchPreflight() {
  return fetchJson<PreflightResponse>(buildUrl("/api/preflight"));
}

export async function fetchPilotBatches(limit = 10) {
  return fetchJson<PilotBatchesResponse>(buildUrl("/api/pilot/batches", { limit }));
}

export async function fetchPilotBatch(batchId: number) {
  return fetchJson<PilotBatchResponse>(buildUrl(`/api/pilot/batches/${batchId}`));
}

export async function postCreatePilotBatch(body: {
  name: string;
  niche: string;
  account_id?: number;
  batch_size?: number;
  use_first_batch_mix?: boolean;
}) {
  return fetchJson<PilotBatchResponse>(buildUrl("/api/pilot/batches"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postRunPilotPending(body?: { batch_id?: number; limit?: number; live_publish?: boolean }) {
  return fetchJson<{ tasks: unknown[]; human_required: string[]; errors: string[] }>(
    buildUrl("/api/pilot/run-pending"),
    { method: "POST", body: JSON.stringify(body ?? {}) },
  );
}

export async function fetchPilotResults(batchId: number) {
  return fetchJson<{ items: Record<string, unknown>[]; disclaimer: string }>(
    buildUrl(`/api/pilot/batches/${batchId}/results`),
  );
}

export async function postTestPublish(body: {
  production_project_id: number;
  account_id: number;
  live?: boolean;
  title?: string;
  caption?: string;
}) {
  return fetchJson(buildUrl("/api/publishing/test-upload"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchCommandStatus() {
  return fetchJson<{ cursor_agent_available: boolean }>(buildUrl("/api/commands/status"));
}

export async function fetchCommands(limit = 50) {
  return fetchJson<{ items: CommandJob[] }>(buildUrl("/api/commands", { limit }), {
    headers: internalHeaders(),
  });
}

export async function postCommand(body: {
  command: string;
  video_id?: number;
  parent_video_id?: number;
  session_id?: string;
  batch_count?: number;
}) {
  return fetchJson<CommandJob>(buildUrl("/api/commands"), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
  });
}

export async function fetchCommandJob(jobKey: string) {
  return fetchJson<CommandJob>(buildUrl(`/api/commands/${jobKey}`), {
    headers: internalHeaders(),
  });
}

export async function fetchCombinationCatalog(owner?: string, pruneMissing?: boolean) {
  return fetchJson<import("@/lib/types").CombinationCatalog>(
    buildUrl("/api/library/combinations/catalog", {
      ...(owner ? { owner } : {}),
      ...(pruneMissing ? { prune_missing: true } : {}),
    }),
  );
}

export async function fetchCombinationStatus(body: {
  owner: string;
  audio_component_id: number;
}) {
  return fetchJson<import("@/lib/types").CombinationStatusResponse>(
    buildUrl("/api/library/combinations/status"),
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function postCombinationRender(body: {
  owner: string;
  audio_component_id: number;
  visual_pack_id: number;
  force?: boolean;
  audio_start_sec?: number;
  audio_end_sec?: number;
  version_label?: string;
}) {
  return fetchJson<import("@/lib/types").CombinationRenderResponse>(
    buildUrl("/api/library/combinations/render"),
    {
      method: "POST",
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(600_000),
    },
  );
}

export async function fetchSharedSyncStatus() {
  return fetchJson<import("@/lib/types").SharedSyncStatus>(buildUrl("/api/library/shared-sync/status"));
}

export async function postSharedSyncPullImport(body?: {
  skip_pull?: boolean;
  dry_run?: boolean;
  auto_only?: boolean;
  force?: boolean;
}) {
  return fetchJson<import("@/lib/types").SharedSyncPullImportResult>(
    buildUrl("/api/library/shared-sync/pull-import"),
    {
      method: "POST",
      body: JSON.stringify(body ?? {}),
      signal: AbortSignal.timeout(600_000),
    },
  );
}

export async function fetchWeekly(weekStart: string, owner: string) {
  return fetchJson<import("@/lib/types").WeeklyResponse>(
    buildUrl("/api/weekly", { week_start: weekStart, owner }),
  );
}

export async function postWeeklySlots(body: {
  week_start: string;
  owner: string;
  replace_week?: boolean;
  expect_full_week?: boolean;
  slots: Array<{
    day: string;
    slot: number;
    speaker: string;
    visual_direction: string;
    image_paths?: string[];
    image_prompt?: string;
    require_stills_first?: boolean;
    brief_text?: string;
  }>;
}) {
  return fetchJson<{ plan_id: number; slots_saved: number; warnings?: string[] }>(buildUrl("/api/weekly/slots"), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
  });
}

export async function fetchWeeklyChatgptPrompt(weekStart: string, owner: string) {
  return fetchJson<{ prompt: string }>(buildUrl("/api/weekly/chatgpt-prompt", { week_start: weekStart, owner }));
}

export async function postWeeklyApplyPaste(body: {
  week_start: string;
  owner: string;
  text: string;
  replace_week?: boolean;
}) {
  return fetchJson<{ plan_id: number; slots_saved: number; warnings?: string[]; parse_warnings?: string[] }>(
    buildUrl("/api/weekly/apply-paste"),
    { method: "POST", body: JSON.stringify(body), headers: internalHeaders() },
  );
}

export async function postWeeklyParsePaste(text: string) {
  return fetchJson<{ slots: unknown[]; warnings: string[]; count: number }>(
    buildUrl("/api/weekly/parse-paste"),
    { method: "POST", body: JSON.stringify({ text }), headers: internalHeaders() },
  );
}

export async function fetchWeeklyPresets(owner?: string) {
  return fetchJson<{ speakers: string[]; visuals: string[] }>(
    buildUrl("/api/weekly/presets", owner ? { owner } : {}),
  );
}

export async function fetchWeeklyExport(weekStart: string, owner: string) {
  return fetchJson<Record<string, unknown>>(buildUrl("/api/weekly/export", { week_start: weekStart, owner }));
}

export async function postWeeklyImport(payload: Record<string, unknown>) {
  return fetchJson<{ plan_id: number; slots_saved: number; warnings?: string[] }>(
    buildUrl("/api/weekly/import"),
    { method: "POST", body: JSON.stringify(payload), headers: internalHeaders() },
  );
}

export async function postWeeklyPreviewBrief(body: Record<string, unknown>) {
  return fetchJson<{ brief: string }>(buildUrl("/api/weekly/preview-brief"), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
  });
}

export async function fetchWeeklyLog(lines = 80) {
  return fetchJson<{ log: string }>(buildUrl("/api/weekly/log", { lines }));
}

export async function fetchWeeklyHealth(params?: { day?: string; owner?: string }) {
  return fetchJson<import("@/lib/types").WeeklyHealthResponse>(
    buildUrl("/api/weekly/health", params),
  );
}

export async function postWeeklyRetrySlot(slotId: number) {
  return fetchJson<{ slot_id: number; status: string; batch?: { count?: number } }>(
    buildUrl(`/api/weekly/slots/${slotId}/retry`),
    {
      method: "POST",
      headers: internalHeaders(),
      signal: AbortSignal.timeout(4 * 60 * 60 * 1000),
    },
  );
}

export async function postWeeklyRunDue(body: {
  day: string;
  owner?: string;
  limit?: number;
  serial?: boolean;
  retry_failed?: boolean;
  wait_complete?: boolean;
}) {
  return fetchJson<{
    day: string;
    count: number;
    deferred?: boolean;
    reason?: string;
    error?: string;
    preflight?: { ok: boolean; issues: string[] };
    submitted: Array<{ slot_id: string; job_key: string }>;
  }>(buildUrl("/api/weekly/run-due"), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
    signal: AbortSignal.timeout(4 * 60 * 60 * 1000),
  });
}

export async function fetchProductionLibrary(params?: {
  limit?: number;
  speaker?: string;
  topic?: string;
  status?: string;
  used?: boolean;
}) {
  return fetchJson<{ items: ProductionLibraryVideo[] }>(buildUrl("/api/library/videos", params));
}

export async function fetchProductionVideo(videoId: number) {
  return fetchJson<ProductionLibraryVideo>(buildUrl(`/api/library/videos/${videoId}`));
}

export async function fetchLibrarySpeakers() {
  return fetchJson<{ items: string[] }>(buildUrl("/api/library/speakers"));
}

export async function postUpdateVideoSpeaker(
  videoId: number,
  body: { speaker: string; remember_correction?: boolean },
) {
  return fetchJson<ProductionLibraryVideo>(buildUrl(`/api/library/videos/${videoId}/speaker`), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
  });
}

export async function postTrimLibraryVideo(
  videoId: number,
  body: {
    start_sec: number;
    end_sec: number;
    mode: "override" | "new_version";
    change_summary?: string;
    version_label?: string;
  },
) {
  return fetchJson<ProductionLibraryVideo>(buildUrl(`/api/library/videos/${videoId}/trim`), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
  });
}

export async function postUpdateVideoPostingStatus(
  videoId: number,
  body: { owner: string } & Partial<Record<"tiktok" | "youtube" | "instagram", boolean>>,
) {
  return fetchJson<ProductionLibraryVideo>(buildUrl(`/api/library/videos/${videoId}/posting-status`), {
    method: "POST",
    body: JSON.stringify(body),
    headers: internalHeaders(),
  });
}

export async function postImportProductionVideo(form: FormData) {
  try {
    const response = await fetch(buildUrl("/api/library/import"), {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(120_000),
      headers: {
        Accept: "application/json",
        ...internalHeaders(),
      },
      cache: "no-store",
    });
    if (!response.ok) {
      let message = `Import failed (${response.status})`;
      try {
        const err = (await response.json()) as { detail?: string };
        if (err.detail) message = err.detail;
      } catch {
        /* ignore */
      }
      return { ok: false as const, error: "offline" as const, message };
    }
    const data = (await response.json()) as ProductionLibraryVideo;
    return { ok: true as const, data };
  } catch {
    return { ok: false as const, error: "offline" as const, message: "Discovery backend is offline." };
  }
}
