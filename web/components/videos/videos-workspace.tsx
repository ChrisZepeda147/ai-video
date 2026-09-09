"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RiskBadge, riskLevel } from "@/components/shared/risk-badge";
import {
  fetchProductionProjects,
  fetchProjectAnalytics,
  postRejectProject,
  postRenderProject,
  postSendProjectToReview,
  productionMediaUrl,
} from "@/lib/api";
import type { ProductionProjectItem, ProjectAnalyticsResponse } from "@/lib/types";

function formatProfileLabel(profile: string): string {
  const labels: Record<string, string> = {
    audio_visuals: "Audio + Visuals",
    source_video_visuals: "Source Video + Visuals",
    original_story: "Original Story",
  };
  return labels[profile] || profile;
}

export function VideosWorkspace() {
  const [projects, setProjects] = useState<ProductionProjectItem[]>([]);
  const [analyticsByProject, setAnalyticsByProject] = useState<Record<number, ProjectAnalyticsResponse>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchProductionProjects();
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setProjects(result.data.items);
    const published = result.data.items.filter((p) => p.status === "approved");
    const analyticsEntries = await Promise.all(
      published.map(async (p) => {
        const res = await fetchProjectAnalytics(p.id);
        return res.ok ? ([p.id, res.data] as const) : null;
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

  return (
    <div>
      {message ? <p className="mb-4 text-sm text-amber-300">{message}</p> : null}
      {loading ? (
        <p className="text-sm text-zinc-500">Loading production projects…</p>
      ) : projects.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No Shorts yet. Build one from <Link href="/create" className="text-violet-300 hover:underline">Create</Link>.
        </div>
      ) : (
        <div className="space-y-4">
          {projects.map((p) => {
            const previewUrl = productionMediaUrl(p.output_path);
            return (
              <article key={p.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex flex-wrap items-start gap-4">
                  {previewUrl ? (
                    <video src={previewUrl} controls className="aspect-[9/16] w-[160px] shrink-0 rounded-lg bg-zinc-950 object-cover" />
                  ) : (
                    <div className="flex aspect-[9/16] w-[160px] shrink-0 items-center justify-center rounded-lg bg-zinc-950 text-xs text-zinc-600">
                      No preview
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-zinc-100">{p.title}</h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      {formatProfileLabel(p.format_profile)} · {p.status}
                      {p.niche ? ` · ${p.niche}` : ""}
                      {p.duration_sec ? ` · ${Math.round(p.duration_sec)}s` : ""}
                    </p>
                    <p className="mt-1 text-xs text-zinc-600">
                      Created {new Date(p.created_at).toLocaleString()}
                      {p.rendered_at ? ` · Rendered ${new Date(p.rendered_at).toLocaleString()}` : ""}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {p.reuse_confidence != null ? (
                        <RiskBadge label="Reuse" score={p.reuse_confidence} level={riskLevel(p.reuse_confidence, true)} />
                      ) : null}
                      {p.rights_confidence != null ? (
                        <RiskBadge label="Rights" score={p.rights_confidence} level={riskLevel(p.rights_confidence)} />
                      ) : null}
                      {p.monetization_confidence != null ? (
                        <RiskBadge label="Monetization" score={p.monetization_confidence} level={riskLevel(p.monetization_confidence)} />
                      ) : null}
                    </div>
                    {p.error_message ? (
                      <p className="mt-2 text-xs text-red-400">{p.error_message}</p>
                    ) : null}
                    {analyticsByProject[p.id]?.latest_metrics ? (
                      <div className="mt-3 rounded-lg border border-zinc-800/80 bg-zinc-950/50 p-3 text-xs text-zinc-400">
                        <p className="font-medium text-zinc-300">
                          Performance: {String(analyticsByProject[p.id].latest_metrics?.performance_score ?? "—")} /{" "}
                          <span className="capitalize">{String(analyticsByProject[p.id].latest_metrics?.performance_tier ?? "—")}</span>
                        </p>
                        <p className="mt-1">
                          {(analyticsByProject[p.id].latest_metrics?.views as number | undefined)?.toLocaleString() ?? "—"} views ·{" "}
                          {String(analyticsByProject[p.id].latest_metrics?.velocity_views_per_day ?? "—")} views/day
                        </p>
                        {analyticsByProject[p.id].performance_signals.length > 0 ? (
                          <ul className="mt-2 list-disc pl-4 text-zinc-500">
                            {analyticsByProject[p.id].performance_signals.slice(0, 3).map((s) => (
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
                      <Link href={`/create?project_id=${p.id}`} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300">Open Project</Link>
                      {["ready", "review", "rendered", "failed", "rejected"].includes(p.status) ? (
                        <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRenderProject(p.id); setBusy(false); load(); setMessage(`Re-render started for #${p.id}`); }} className="rounded bg-violet-600 px-3 py-1 text-xs text-white disabled:opacity-50">Re-render</button>
                      ) : null}
                      {p.output_path && p.status !== "review" ? (
                        <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postSendProjectToReview(p.id); setBusy(false); load(); setMessage(`Project #${p.id} sent to review`); }} className="rounded border border-sky-500/40 px-3 py-1 text-xs text-sky-300 disabled:opacity-50">Send to Review</button>
                      ) : null}
                      {p.status === "review" ? (
                        <Link href="/review" className="rounded border border-emerald-500/40 px-3 py-1 text-xs text-emerald-300">Review Queue</Link>
                      ) : null}
                      {p.status === "rejected" ? (
                        <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRejectProject(p.id); setBusy(false); load(); }} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-400 disabled:opacity-50">Archive</button>
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
