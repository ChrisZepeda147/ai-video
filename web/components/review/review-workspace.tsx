"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RiskBadge, riskLevel } from "@/components/shared/risk-badge";
import {
  fetchProductionProjects,
  fetchVisualsReview,
  getMediaUrl,
  postApproveProject,
  postApproveVisuals,
  postRejectProject,
  postRejectVisuals,
  postRenderProject,
  productionMediaUrl,
} from "@/lib/api";
import { PublishDialog } from "@/components/publishing/publish-dialog";
import type { ProductionProjectItem, VisualAssetItem } from "@/lib/types";

type Tab = "visuals" | "shorts" | "approved";

export function ReviewWorkspace() {
  const [tab, setTab] = useState<Tab>("visuals");
  const [assets, setAssets] = useState<VisualAssetItem[]>([]);
  const [projects, setProjects] = useState<ProductionProjectItem[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [approved, setApproved] = useState<ProductionProjectItem[]>([]);
  const [publishProject, setPublishProject] = useState<ProductionProjectItem | null>(null);

  const loadVisuals = useCallback(async () => {
    setLoading(true);
    const result = await fetchVisualsReview({ asset_type: filter || undefined });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      setAssets([]);
      return;
    }
    setAssets(result.data.items);
    setSelected(new Set());
  }, [filter]);

  const loadShorts = useCallback(async () => {
    setLoading(true);
    const result = await fetchProductionProjects({ status: "review" });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      setProjects([]);
      return;
    }
    setProjects(result.data.items);
  }, []);

  const loadApproved = useCallback(async () => {
    setLoading(true);
    const result = await fetchProductionProjects({ status: "approved" });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      setApproved([]);
      return;
    }
    setApproved(result.data.items);
  }, []);

  useEffect(() => {
    if (tab === "visuals") loadVisuals();
    else if (tab === "shorts") loadShorts();
    else loadApproved();
  }, [tab, loadVisuals, loadShorts, loadApproved]);

  async function runVisualBatch(action: "approve" | "reject") {
    if (selected.size === 0 || busy) return;
    setBusy(true);
    const ids = Array.from(selected);
    const result =
      action === "approve"
        ? await postApproveVisuals(ids)
        : await postRejectVisuals(ids);
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`${action}: ${result.data.count} asset(s)`);
    await loadVisuals();
  }

  return (
    <div>
      <div className="mb-4 flex gap-2">
        <button
          type="button"
          onClick={() => setTab("visuals")}
          className={`rounded-lg px-4 py-2 text-sm ${tab === "visuals" ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
        >
          Visual assets
        </button>
        <button
          type="button"
          onClick={() => setTab("shorts")}
          className={`rounded-lg px-4 py-2 text-sm ${tab === "shorts" ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
        >
          Finished Shorts
        </button>
        <button
          type="button"
          onClick={() => setTab("approved")}
          className={`rounded-lg px-4 py-2 text-sm ${tab === "approved" ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
        >
          Approved / Publish
        </button>
      </div>

      {publishProject ? (
        <PublishDialog
          project={publishProject}
          onClose={() => setPublishProject(null)}
          onPublished={(msg) => {
            setMessage(msg);
            loadApproved();
          }}
        />
      ) : null}

      {message ? <p className="mb-4 text-sm text-amber-300">{message}</p> : null}

      {tab === "visuals" ? (
        <>
          <section className="mb-4 flex flex-wrap gap-2">
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
            >
              <option value="">All types</option>
              <option value="image">Images</option>
              <option value="video">Videos</option>
            </select>
            {selected.size > 0 ? (
              <>
                <button type="button" disabled={busy} onClick={() => runVisualBatch("approve")} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-50">Batch Approve</button>
                <button type="button" disabled={busy} onClick={() => runVisualBatch("reject")} className="rounded-lg border border-red-500/40 px-3 py-2 text-sm text-red-300 disabled:opacity-50">Batch Reject</button>
              </>
            ) : null}
          </section>

          {loading ? (
            <p className="text-sm text-zinc-500">Loading review queue…</p>
          ) : assets.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
              No assets waiting review. Create a generation job, generate outputs in Cursor, then import.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {assets.map((a) => {
                const url = getMediaUrl(a.media_url);
                return (
                  <article key={a.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 overflow-hidden">
                    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
                      <label className="flex items-center gap-2 text-xs text-zinc-400">
                        <input
                          type="checkbox"
                          checked={selected.has(a.id)}
                          onChange={() =>
                            setSelected((prev) => {
                              const next = new Set(prev);
                              if (next.has(a.id)) next.delete(a.id);
                              else next.add(a.id);
                              return next;
                            })
                          }
                        />
                        #{a.id} · {a.asset_type}
                      </label>
                      <span className="text-xs capitalize text-zinc-500">{a.status}</span>
                    </div>
                    <div className="aspect-[9/16] bg-zinc-950 flex items-center justify-center">
                      {url && a.asset_type === "image" ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={url} alt="" className="h-full w-full object-cover" />
                      ) : url && a.asset_type === "video" ? (
                        <video src={url} controls className="h-full w-full object-cover" />
                      ) : (
                        <span className="text-xs text-zinc-600">No preview</span>
                      )}
                    </div>
                    <p className="line-clamp-3 p-3 text-xs text-zinc-400">{a.prompt}</p>
                    <div className="flex gap-2 border-t border-zinc-800 p-2">
                      <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postApproveVisuals([a.id]); setBusy(false); await loadVisuals(); }} className="flex-1 rounded bg-emerald-600/80 py-1 text-xs text-white disabled:opacity-50">Approve</button>
                      <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRejectVisuals([a.id]); setBusy(false); await loadVisuals(); }} className="flex-1 rounded border border-red-500/30 py-1 text-xs text-red-300 disabled:opacity-50">Reject</button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </>
      ) : tab === "approved" ? (
        loading ? (
          <p className="text-sm text-zinc-500">Loading approved Shorts…</p>
        ) : approved.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
            No approved Shorts ready to publish yet.
          </div>
        ) : (
          <div className="space-y-4">
            {approved.map((p) => {
              const url = productionMediaUrl(p.output_path);
              return (
                <article key={p.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex flex-wrap items-start gap-4">
                    {url ? (
                      <video src={url} controls className="aspect-[9/16] w-[180px] rounded-lg bg-zinc-950 object-cover" />
                    ) : null}
                    <div className="min-w-0 flex-1">
                      <h3 className="font-semibold text-zinc-100">{p.title}</h3>
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
                      <button
                        type="button"
                        onClick={() => setPublishProject(p)}
                        className="mt-3 rounded bg-emerald-600 px-4 py-2 text-sm text-white"
                      >
                        Publish
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )
      ) : loading ? (
        <p className="text-sm text-zinc-500">Loading finished Shorts…</p>
      ) : projects.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No Shorts awaiting review. Render from <Link href="/create" className="text-violet-300 hover:underline">Create</Link>.
        </div>
      ) : (
        <div className="space-y-4">
          {projects.map((p) => {
            const url = productionMediaUrl(p.output_path);
            return (
              <article key={p.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex flex-wrap items-start gap-4">
                  {url ? (
                    <video src={url} controls className="aspect-[9/16] w-[180px] rounded-lg bg-zinc-950 object-cover" />
                  ) : null}
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-zinc-100">{p.title}</h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      {p.format_profile} · {p.duration_sec ? `${Math.round(p.duration_sec)}s` : "—"}
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
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postApproveProject(p.id); setBusy(false); setMessage(`Approved project #${p.id}`); await loadShorts(); }} className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-50">Approve</button>
                      <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRejectProject(p.id); setBusy(false); setMessage(`Rejected project #${p.id}`); await loadShorts(); }} className="rounded border border-red-500/40 px-3 py-1 text-xs text-red-300 disabled:opacity-50">Reject</button>
                      <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRenderProject(p.id); setBusy(false); await loadShorts(); setMessage(`Re-rendered project #${p.id}`); }} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300 disabled:opacity-50">Re-render</button>
                      <Link href={`/create?project_id=${p.id}`} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300">Open Project</Link>
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
