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

const DEFAULT_API_URL = "http://localhost:8000";

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || DEFAULT_API_URL;
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

async function fetchJson<T>(url: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(url, {
      ...init,
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
        const err = (await response.json()) as { detail?: string };
        if (err.detail) message = err.detail;
      } catch {
        /* ignore */
      }
      return { ok: false, error: "offline", message };
    }
    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch {
    return {
      ok: false,
      error: "offline",
      message: "Discovery backend is offline.",
    };
  }
}

export async function fetchHealth(): Promise<ApiResult<{ status: string }>> {
  return fetchJson<{ status: string }>(buildUrl("/health"));
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

export async function fetchPublishingAccounts(params?: { platform?: string }) {
  return fetchJson<PublishingAccountsResponse>(buildUrl("/api/accounts", params));
}

export async function postConnectAccount(platform: string, body: { display_name: string; niche?: string }) {
  return fetchJson<{ auth_url: string; state: string; instructions: string }>(
    buildUrl(`/api/accounts/${platform}/connect`),
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
  return `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function fetchAnalyticsOverview(params?: {
  platform?: string;
  account_id?: number;
  niche?: string;
}) {
  return fetchJson<AnalyticsOverview>(buildUrl("/api/analytics/overview", params));
}

export async function fetchAnalyticsPosts(params?: {
  platform?: string;
  account_id?: number;
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
