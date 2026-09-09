"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RiskBadge, riskLevel } from "@/components/shared/risk-badge";
import {
  fetchProjectAnalytics,
  fetchVideoLibrary,
  postImportVideos,
  postRejectProject,
  postRenderProject,
  postSendProjectToReview,
  productionMediaUrl,
} from "@/lib/api";
import type { ProjectAnalyticsResponse, VideoLibraryItem, VideoLibraryResponse } from "@/lib/types";

function formatProfileLabel(profile: string): string {
  const labels: Record<string, string> = {
    audio_visuals: "Audio + Visuals",
    source_video_visuals: "Source Video + Visuals",
    original_story: "Original Story",
  };
  return labels[profile] || profile;
}

function sourceLabel(item: VideoLibraryItem): string {
  if (item.source === "legacy") return "Legacy pipeline";
  if (item.origin_type === "legacy") return "Imported legacy";
  return "Site pipeline";
}

function canAddToSite(item: VideoLibraryItem): boolean {
  return item.source === "legacy" && item.preview_available;
}

export function VideosWorkspace() {
  const [items, setItems] = useState<VideoLibraryItem[]>([]);
  const [summary, setSummary] = useState<VideoLibraryResponse["summary"] | null>(null);
  const [analyticsByProject, setAnalyticsByProject] = useState<Record<number, ProjectAnalyticsResponse>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const readyToAdd = useMemo(() => items.filter(canAddToSite), [items]);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchVideoLibrary({ include_missing: true, limit: 100 });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setItems(result.data.items);
    setSummary(result.data.summary);
    const published = result.data.items.filter(
      (item) => item.source === "production" && item.project_id != null && item.status === "approved",
    );
    const analyticsEntries = await Promise.all(
      published.map(async (item) => {
        const res = await fetchProjectAnalytics(item.project_id!);
        return res.ok ? ([item.project_id!, res.data] as const) : null;
      }),
    );
    const map: Record<number, ProjectAnalyticsResponse> = {};
    for (const entry of analyticsEntries) {
      if (entry) map[entry[0]] = entry[1];
    }
    setAnalyticsByProject(map);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function importVideos(options?: { slug?: string; rebuild_catalog?: boolean }) {
    setBusy(true);
    setMessage(null);
    const result = await postImportVideos({
      slug: options?.slug,
      rebuild_catalog: options?.rebuild_catalog ?? true,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    const { imported_count, skipped_count } = result.data;
    if (imported_count > 0) {
      setMessage(`Added ${imported_count} video${imported_count === 1 ? "" : "s"} to the site.`);
    } else if (skipped_count > 0) {
      setMessage("No new videos to add — ready items may already be on the site.");
    } else {
      setMessage("No rendered MP4s found yet. Finish a render in Cursor first.");
    }
    await load();
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {summary ? (
          <p className="text-sm text-zinc-500">
            {summary.preview_ready} ready to preview · {summary.production} on site · {summary.legacy} in legacy catalog
            {summary.missing_files > 0 ? ` · ${summary.missing_files} waiting on MP4 files` : ""}
          </p>
        ) : null}
        <button
          type="button"
          disabled={busy || readyToAdd.length === 0}
          onClick={() => importVideos({ rebuild_catalog: true })}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Adding…" : readyToAdd.length > 0 ? `Add ${readyToAdd.length} ready to site` : "Add ready to site"}
        </button>
      </div>
      {message ? <p className="mb-4 text-sm text-emerald-300">{message}</p> : null}
      {loading ? (
        <p className="text-sm text-zinc-500">Loading video library…</p>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No Shorts yet. Build one from <Link href="/create" className="text-violet-300 hover:underline">Create</Link>
          {" "}or render with a legacy script, then click <strong className="text-zinc-300">Add ready to site</strong>.
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => {
            const previewUrl = item.preview_available ? productionMediaUrl(item.output_path) : null;
            const projectId = item.project_id ?? null;
            const addable = canAddToSite(item);
            return (
              <article key={item.key} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex flex-wrap items-start gap-4">
                  {previewUrl ? (
                    <video src={previewUrl} controls className="aspect-[9/16] w-[160px] shrink-0 rounded-lg bg-zinc-950 object-cover" />
                  ) : (
                    <div className="flex aspect-[9/16] w-[160px] shrink-0 items-center justify-center rounded-lg bg-zinc-950 px-3 text-center text-xs text-zinc-600">
                      MP4 not on this machine
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold text-zinc-100">{item.title}</h3>
                      <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
                        {sourceLabel(item)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">
                      {formatProfileLabel(item.format_profile)} · {item.status}
                      {item.niche ? ` · ${item.niche}` : ""}
                      {item.duration_sec ? ` · ${Math.round(item.duration_sec)}s` : ""}
                    </p>
                    <p className="mt-1 text-xs text-zinc-600">
                      {item.created_at ? `Created ${new Date(item.created_at).toLocaleString()}` : `Slug ${item.slug}`}
                      {item.rendered_at ? ` · Rendered ${new Date(item.rendered_at).toLocaleString()}` : ""}
                    </p>
                    {item.output_paths.length > 1 ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.output_paths.map((path, index) => {
                          const partUrl = productionMediaUrl(path);
                          return partUrl ? (
                            <a
                              key={path}
                              href={partUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="rounded border border-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-200"
                            >
                              Part {index + 1}
                            </a>
                          ) : (
                            <span key={path} className="rounded border border-zinc-900 px-2 py-0.5 text-[11px] text-zinc-600">
                              Part {index + 1} missing
                            </span>
                          );
                        })}
                      </div>
                    ) : null}
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.reuse_confidence != null ? (
                        <RiskBadge label="Reuse" score={item.reuse_confidence} level={riskLevel(item.reuse_confidence, true)} />
                      ) : null}
                      {item.rights_confidence != null ? (
                        <RiskBadge label="Rights" score={item.rights_confidence} level={riskLevel(item.rights_confidence)} />
                      ) : null}
                      {item.monetization_confidence != null ? (
                        <RiskBadge label="Monetization" score={item.monetization_confidence} level={riskLevel(item.monetization_confidence)} />
                      ) : null}
                    </div>
                    {!item.preview_available && item.missing_paths.length > 0 ? (
                      <p className="mt-2 text-xs text-amber-300/90">
                        Render or copy MP4s locally, then click <strong>Add ready to site</strong> above.
                      </p>
                    ) : null}
                    {item.error_message ? (
                      <p className="mt-2 text-xs text-red-400">{item.error_message}</p>
                    ) : null}
                    {projectId && analyticsByProject[projectId]?.latest_metrics ? (
                      <div className="mt-3 rounded-lg border border-zinc-800/80 bg-zinc-950/50 p-3 text-xs text-zinc-400">
                        <p className="font-medium text-zinc-300">
                          Performance: {String(analyticsByProject[projectId].latest_metrics?.performance_score ?? "—")} /{" "}
                          <span className="capitalize">{String(analyticsByProject[projectId].latest_metrics?.performance_tier ?? "—")}</span>
                        </p>
                        <p className="mt-1">
                          {(analyticsByProject[projectId].latest_metrics?.views as number | undefined)?.toLocaleString() ?? "—"} views ·{" "}
                          {String(analyticsByProject[projectId].latest_metrics?.velocity_views_per_day ?? "—")} views/day
                        </p>
                        {analyticsByProject[projectId].performance_signals.length > 0 ? (
                          <ul className="mt-2 list-disc pl-4 text-zinc-500">
                            {analyticsByProject[projectId].performance_signals.slice(0, 3).map((s) => (
                              <li key={s}>{s}</li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {previewUrl ? (
                        <a href={previewUrl} target="_blank" rel="noreferrer" className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300">Preview</a>
                      ) : null}
                      {addable ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => importVideos({ slug: item.slug, rebuild_catalog: false })}
                          className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                        >
                          Add to site
                        </button>
                      ) : null}
                      {projectId ? (
                        <>
                          <Link href={`/create?project_id=${projectId}`} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300">Open Project</Link>
                          {["ready", "review", "rendered", "failed", "rejected"].includes(item.status) ? (
                            <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRenderProject(projectId); setBusy(false); load(); setMessage(`Re-render started for #${projectId}`); }} className="rounded bg-violet-600 px-3 py-1 text-xs text-white disabled:opacity-50">Re-render</button>
                          ) : null}
                          {item.output_path && item.status !== "review" ? (
                            <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postSendProjectToReview(projectId); setBusy(false); load(); setMessage(`Project #${projectId} sent to review`); }} className="rounded border border-sky-500/40 px-3 py-1 text-xs text-sky-300 disabled:opacity-50">Send to Review</button>
                          ) : null}
                          {item.status === "review" ? (
                            <Link href="/review" className="rounded border border-emerald-500/40 px-3 py-1 text-xs text-emerald-300">Review Queue</Link>
                          ) : null}
                          {item.status === "rejected" ? (
                            <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRejectProject(projectId); setBusy(false); load(); }} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-400 disabled:opacity-50">Archive</button>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
