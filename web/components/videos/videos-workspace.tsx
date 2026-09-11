"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RiskBadge, riskLevel } from "@/components/shared/risk-badge";
import { VideoItemEditor } from "@/components/videos/video-item-editor";
import { VideoLinkDialog } from "@/components/videos/video-link-dialog";
import {
  fetchLibrarySpeakers,
  fetchProjectAnalytics,
  fetchPublishingOwner,
  fetchVideoLibrary,
  postDeleteVideoLibraryItem,
  postImportVideos,
  postPruneVideoCatalog,
  postRejectProject,
  postRenderProject,
  postSendProjectToReview,
  productionMediaUrl,
} from "@/lib/api";
import { displayMediaPath, formatDuration, formatMediaKind } from "@/lib/format";
import type { ProjectAnalyticsResponse, VideoLibraryItem, VideoLibraryResponse } from "@/lib/types";

type SourceFilter = "all" | "site" | "library" | "legacy";
type MediaFilter = "all" | "video" | "video_audio" | "audio";

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
  if (item.source === "library") return "Production library";
  if (item.origin_type === "legacy") return "Imported legacy";
  return "Site pipeline";
}

function canAddToSite(item: VideoLibraryItem): boolean {
  return item.source === "legacy" && item.preview_available && item.media_kind !== "audio";
}

function itemHref(item: VideoLibraryItem): string | null {
  if (item.library_id) return `/library/${item.library_id}`;
  if (item.project_id) return `/create?project_id=${item.project_id}`;
  return null;
}

export function VideosWorkspace() {
  const [items, setItems] = useState<VideoLibraryItem[]>([]);
  const [summary, setSummary] = useState<VideoLibraryResponse["summary"] | null>(null);
  const [analyticsByProject, setAnalyticsByProject] = useState<Record<number, ProjectAnalyticsResponse>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [mediaFilter, setMediaFilter] = useState<MediaFilter>("video");
  const [showMissing, setShowMissing] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [confirmDeleteKey, setConfirmDeleteKey] = useState<string | null>(null);
  const [linkKey, setLinkKey] = useState<string | null>(null);
  const [localOwner, setLocalOwner] = useState<string>("chris");
  const [speakerOptions, setSpeakerOptions] = useState<string[]>([]);

  const readyToAdd = useMemo(() => items.filter(canAddToSite), [items]);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (!showMissing && !item.preview_available) return false;
      if (sourceFilter === "site" && item.source !== "production") return false;
      if (sourceFilter === "library" && item.source !== "library") return false;
      if (sourceFilter === "legacy" && item.source !== "legacy") return false;
      if (mediaFilter === "video" && item.media_kind !== "video") return false;
      if (mediaFilter === "video_audio" && item.media_kind !== "video_audio") return false;
      if (mediaFilter === "audio" && item.media_kind !== "audio") return false;
      return true;
    });
  }, [items, showMissing, sourceFilter, mediaFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    const [result, speakersResult] = await Promise.all([
      fetchVideoLibrary({ include_missing: showMissing, limit: 200 }),
      fetchLibrarySpeakers(),
    ]);
    setLoading(false);
    if (speakersResult.ok) setSpeakerOptions(speakersResult.data.items);
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
  }, [showMissing]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    fetchPublishingOwner().then((result) => {
      if (result.ok && result.data.owner) setLocalOwner(result.data.owner);
    });
  }, []);

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

  async function handleDeleteItem(item: VideoLibraryItem) {
    setBusy(true);
    setMessage(null);
    const result = await postDeleteVideoLibraryItem({
      source: item.source,
      library_id: item.library_id ?? undefined,
      project_id: item.project_id ?? undefined,
      legacy_id: item.legacy_id ?? undefined,
      slug: item.slug,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setConfirmDeleteKey(null);
    setEditingKey(null);
    setMessage(`Removed ${item.speaker || item.title} from Videos.`);
    await load();
  }

  async function handlePruneMissing() {
    setBusy(true);
    setMessage(null);
    const result = await postPruneVideoCatalog();
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    const removed = result.data.legacy_catalog.removed;
    setMessage(
      removed > 0
        ? `Removed ${removed} invalid legacy catalog row(s).`
        : "No invalid legacy rows to remove.",
    );
    await load();
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {summary ? (
          <p className="text-sm text-zinc-500">
            {summary.preview_ready} preview-ready · {summary.production ?? 0} site ·{" "}
            {summary.library ?? 0} library · {summary.legacy} legacy
            {summary.missing_files > 0 ? ` · ${summary.missing_files} missing files` : ""}
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
        <button
          type="button"
          disabled={busy}
          onClick={() => void handlePruneMissing()}
          className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
        >
          Remove invalid legacy
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <label className="text-xs text-zinc-500">
          Source
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
            className="ml-2 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-200"
          >
            <option value="all">All</option>
            <option value="site">Site pipeline</option>
            <option value="library">Production library</option>
            <option value="legacy">Legacy pipeline</option>
          </select>
        </label>
        <label className="text-xs text-zinc-500">
          Media
          <select
            value={mediaFilter}
            onChange={(e) => setMediaFilter(e.target.value as MediaFilter)}
            className="ml-2 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-200"
          >
            <option value="all">All</option>
            <option value="video">Video</option>
            <option value="video_audio">Video / Audio</option>
            <option value="audio">Audio</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input type="checkbox" checked={showMissing} onChange={(e) => setShowMissing(e.target.checked)} />
          Show invalid / missing files
        </label>
      </div>

      {message ? <p className="mb-4 text-sm text-emerald-300">{message}</p> : null}
      {loading ? (
        <p className="text-sm text-zinc-500">Loading video library…</p>
      ) : filteredItems.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No items match filters. Build from{" "}
          <Link href="/create" className="text-violet-300 hover:underline">
            Make Short
          </Link>{" "}
          or{" "}
          <Link href="/library" className="text-violet-300 hover:underline">
            Library
          </Link>
          , then refresh.
        </div>
      ) : (
        <div className="space-y-4">
          {filteredItems.map((item) => {
            const path = item.display_path || displayMediaPath(item.output_path);
            const previewUrl =
              item.preview_available && item.media_kind !== "audio"
                ? productionMediaUrl(item.output_path)
                : null;
            const audioUrl =
              item.preview_available && item.media_kind === "audio"
                ? productionMediaUrl(item.output_path)
                : null;
            const projectId = item.project_id ?? null;
            const addable = canAddToSite(item);
            const href = itemHref(item);
            const isEditing = editingKey === item.key;
            const isLinking = linkKey === item.key;
            const displayTitle = item.speaker || item.title;

            const cardInner = (
              <>
                <div className="flex flex-wrap items-start gap-4">
                  {previewUrl ? (
                    <video
                      src={previewUrl}
                      controls
                      className="aspect-[9/16] w-[160px] shrink-0 rounded-lg bg-zinc-950 object-cover"
                    />
                  ) : audioUrl ? (
                    <div className="flex w-[160px] shrink-0 flex-col gap-2 rounded-lg bg-zinc-950 p-3">
                      <span className="text-[10px] uppercase tracking-wide text-zinc-500">Audio</span>
                      <audio src={audioUrl} controls className="w-full" />
                    </div>
                  ) : (
                    <div className="flex aspect-[9/16] w-[160px] shrink-0 items-center justify-center rounded-lg bg-zinc-950 px-3 text-center text-xs text-zinc-600">
                      File missing
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold text-zinc-100">{displayTitle}</h3>
                      {item.speaker && item.speaker !== item.title ? (
                        <span className="text-xs text-zinc-500">({item.title})</span>
                      ) : null}
                      <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
                        {sourceLabel(item)}
                      </span>
                      {item.media_kind ? (
                        <span className="rounded-full border border-zinc-800 px-2 py-0.5 text-[10px] uppercase text-zinc-500">
                          {formatMediaKind(item.media_kind)}
                        </span>
                      ) : null}
                    </div>
                    {path ? (
                      <p className="mt-1 break-all font-mono text-xs text-violet-300/90">{path}</p>
                    ) : null}
                    <p className="mt-1 text-xs text-zinc-500">
                      {formatProfileLabel(item.format_profile)} · {item.status}
                      {item.niche ? ` · ${item.niche}` : ""}
                      {item.duration_sec ? ` · ${formatDuration(item.duration_sec)}` : ""}
                    </p>
                    <p className="mt-1 text-xs text-zinc-600">
                      Slug {item.slug}
                      {item.created_at ? ` · ${new Date(item.created_at).toLocaleString()}` : ""}
                    </p>
                    {item.reuse_confidence != null ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <RiskBadge
                          label="Reuse"
                          score={item.reuse_confidence}
                          level={riskLevel(item.reuse_confidence, true)}
                        />
                      </div>
                    ) : null}
                    {!item.preview_available && item.missing_paths.length > 0 ? (
                      <p className="mt-2 text-xs text-amber-300/90">
                        Missing: {item.missing_paths.map((p) => displayMediaPath(p) || p).join(", ")}
                      </p>
                    ) : null}
                    {item.published_to && item.published_to.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.published_to.map((link) => (
                          <a
                            key={`${link.job_id}-${link.account_id}`}
                            href={link.platform_url || "#"}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="rounded border border-sky-800/60 bg-sky-950/30 px-2 py-0.5 text-[11px] text-sky-300"
                          >
                            {link.account_display_name || link.platform} · {link.platform}
                          </a>
                        ))}
                      </div>
                    ) : null}
                    {projectId && analyticsByProject[projectId]?.latest_metrics ? (
                      <p className="mt-2 text-xs text-zinc-400">
                        {(analyticsByProject[projectId].latest_metrics?.views as number | undefined)?.toLocaleString() ??
                          "—"}{" "}
                        views
                      </p>
                    ) : null}
                    {item.output_paths.length > 1 ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.output_paths.map((partPath, index) => {
                          const partUrl = productionMediaUrl(partPath);
                          const partLabel = displayMediaPath(partPath) || `Part ${index + 1}`;
                          return partUrl ? (
                            <a
                              key={partPath}
                              href={partUrl}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="rounded border border-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-200"
                            >
                              {partLabel}
                            </a>
                          ) : (
                            <span
                              key={partPath}
                              className="rounded border border-zinc-900 px-2 py-0.5 text-[11px] text-zinc-600"
                            >
                              {partLabel} (missing)
                            </span>
                          );
                        })}
                      </div>
                    ) : null}
                    {isLinking ? (
                      <VideoLinkDialog
                        item={item}
                        localOwner={localOwner}
                        onClose={() => setLinkKey(null)}
                        onLinked={(msg) => {
                          setMessage(msg);
                          void load();
                        }}
                      />
                    ) : null}
                    {isEditing ? (
                      <VideoItemEditor
                        item={item}
                        speakerOptions={speakerOptions}
                        busy={busy}
                        onBusy={setBusy}
                        onSaved={(updated) => {
                          setItems((prev) => prev.map((row) => (row.key === updated.key ? updated : row)));
                          setEditingKey(null);
                          setMessage(`Updated ${updated.speaker || updated.title}`);
                        }}
                        onCancel={() => setEditingKey(null)}
                      />
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditingKey(isEditing ? null : item.key);
                          setLinkKey(null);
                        }}
                        className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setLinkKey(isLinking ? null : item.key);
                          setEditingKey(null);
                          setConfirmDeleteKey(null);
                        }}
                        className="rounded border border-sky-700/60 px-3 py-1 text-xs text-sky-300 hover:bg-sky-950/40"
                      >
                        Link post
                      </button>
                      {previewUrl || audioUrl ? (
                        <a
                          href={(previewUrl || audioUrl)!}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
                        >
                          Open file
                        </a>
                      ) : null}
                      {href ? (
                        <Link
                          href={href}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded border border-violet-700 px-3 py-1 text-xs text-violet-300"
                        >
                          {item.library_id ? "Library detail" : "Open project"}
                        </Link>
                      ) : null}
                      {addable ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={(e) => {
                            e.stopPropagation();
                            void importVideos({ slug: item.slug, rebuild_catalog: false });
                          }}
                          className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                        >
                          Add to site
                        </button>
                      ) : null}
                      {confirmDeleteKey === item.key ? (
                        <div className="flex flex-wrap items-center gap-2 rounded border border-red-900/60 bg-red-950/30 px-2 py-1">
                          <span className="text-xs text-red-200">Are you sure?</span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleDeleteItem(item);
                            }}
                            className="rounded bg-red-600 px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
                          >
                            Yes, remove
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteKey(null);
                            }}
                            className="rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-300"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteKey(item.key);
                            setEditingKey(null);
                          }}
                          className="rounded border border-red-900/50 px-3 py-1 text-xs text-red-300 hover:bg-red-950/40 disabled:opacity-50"
                        >
                          Delete
                        </button>
                      )}
                      {projectId ? (
                        <>
                          {["ready", "review", "rendered", "failed", "rejected"].includes(item.status) ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={async (e) => {
                                e.stopPropagation();
                                setBusy(true);
                                await postRenderProject(projectId);
                                setBusy(false);
                                load();
                                setMessage(`Re-render started for #${projectId}`);
                              }}
                              className="rounded bg-violet-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                            >
                              Re-render
                            </button>
                          ) : null}
                          {item.output_path && item.status !== "review" ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={async (e) => {
                                e.stopPropagation();
                                setBusy(true);
                                await postSendProjectToReview(projectId);
                                setBusy(false);
                                load();
                                setMessage(`Project #${projectId} sent to review`);
                              }}
                              className="rounded border border-sky-500/40 px-3 py-1 text-xs text-sky-300 disabled:opacity-50"
                            >
                              Send to Review
                            </button>
                          ) : null}
                          {item.status === "review" ? (
                            <Link
                              href="/review"
                              onClick={(e) => e.stopPropagation()}
                              className="rounded border border-emerald-500/40 px-3 py-1 text-xs text-emerald-300"
                            >
                              Review Queue
                            </Link>
                          ) : null}
                          {item.status === "rejected" ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={async (e) => {
                                e.stopPropagation();
                                setBusy(true);
                                await postRejectProject(projectId);
                                setBusy(false);
                                load();
                              }}
                              className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-400 disabled:opacity-50"
                            >
                              Archive
                            </button>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  </div>
                </div>
              </>
            );

            return (
              <article
                key={item.key}
                className={`rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 ${
                  href && item.preview_available ? "cursor-pointer hover:border-zinc-700" : ""
                }`}
                onClick={() => {
                  if (isEditing || isLinking) return;
                  if (href && item.preview_available) window.location.href = href;
                }}
                onKeyDown={(e) => {
                  if (isEditing) return;
                  if (href && item.preview_available && (e.key === "Enter" || e.key === " ")) {
                    window.location.href = href;
                  }
                }}
                role={href && item.preview_available && !isEditing ? "link" : undefined}
                tabIndex={href && item.preview_available && !isEditing ? 0 : undefined}
              >
                {cardInner}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
