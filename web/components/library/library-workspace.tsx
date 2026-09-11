"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import { formatDuration, formatTimecode } from "@/lib/format";
import {
  fetchProductionLibrary,
  fetchSharedSyncStatus,
  postImportProductionVideo,
  postSharedSyncPullImport,
  productionMediaUrl,
} from "@/lib/api";
import type { ProductionLibraryVideo, SharedSyncStatus } from "@/lib/types";

export function LibraryWorkspace() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [videos, setVideos] = useState<ProductionLibraryVideo[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<SharedSyncStatus | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchProductionLibrary({ limit: 200 });
    setLoading(false);
    setBackendOnline(result.ok);
    if (result.ok) setVideos(result.data.items);
    const sync = await fetchSharedSyncStatus();
    if (sync.ok) setSyncStatus(sync.data);
  }, []);

  const runAutoSync = useCallback(async () => {
    if (backendOnline === false) return;
    const result = await postSharedSyncPullImport({ auto_only: true });
    if (!result.ok) return;
    if (result.data.skipped) {
      if (result.data.status) setSyncStatus(result.data.status);
      return;
    }
    setSyncStatus(result.data.status);
    const imp = result.data.import;
    if (imp && imp.imported > 0) {
      setMessage(
        `Shared library auto-sync: ${imp.imported} new video(s) imported (${imp.skipped} already in library).`,
      );
      await load();
    }
  }, [backendOnline, load]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (backendOnline !== true) return;
    void runAutoSync();
  }, [backendOnline, runAutoSync]);

  async function handleSyncShared() {
    setSyncBusy(true);
    setMessage(null);
    const result = await postSharedSyncPullImport();
    setSyncBusy(false);
    if (!result.ok) {
      setMessage(typeof result.message === "string" ? result.message : "Shared library sync failed.");
      return;
    }
    const imp = result.data.import;
    if (!imp) {
      setMessage("Sync finished — no import details returned.");
      await load();
      return;
    }
    setSyncStatus(result.data.status);
    const pullNote = result.data.pull_warning ? ` Pull note: ${result.data.pull_warning}.` : "";
    if (imp.found === 0) {
      setMessage(
        `No shared packages on disk yet.${pullNote} Each machine exports with SHARED_LIBRARY_EXPORT_OWNER then push-shared.`,
      );
    } else {
      setMessage(
        `Shared sync: ${imp.imported} imported, ${imp.skipped} already in library, ${imp.found} packages found (Stephen + Chris)` +
          (imp.errors ? `, ${imp.errors} errors` : "") +
          pullNote,
      );
    }
    await load();
  }

  const ownerSummary = syncStatus?.owners
    ? Object.entries(syncStatus.owners)
        .filter(([, stats]) => stats.packages_on_disk > 0)
        .map(([name, stats]) => `${name}: ${stats.packages_on_disk}`)
        .join(" · ")
    : null;

  const Sync_Health = syncStatus?.health
    ? {
        Health_Ok: Boolean(syncStatus.health.ok),
        Health_Label: syncStatus.health.label ?? "unknown",
        Health_Summary: syncStatus.health.summary ?? "",
      }
    : null;

  async function handleUpload(file: File) {
    setBusy(true);
    setMessage(null);
    const form = new FormData();
    form.append("file", file);
    form.append("extract_audio", "true");
    const result = await postImportProductionVideo(form);
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Imported ${result.data.video_key} — ${result.data.title}`);
    await load();
  }

  return (
    <div className="space-y-6">
      {backendOnline === false ? <BackendOfflineBanner message="Start the API, then refresh." /> : null}

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-zinc-100">Brother sync (code + videos)</h3>
              {Sync_Health ? (
                <span
                  className={
                    Sync_Health.Health_Ok
                      ? "rounded-full border border-emerald-700 bg-emerald-600/20 px-2 py-0.5 text-[11px] font-medium text-emerald-100"
                      : "rounded-full border border-amber-700 bg-amber-600/20 px-2 py-0.5 text-[11px] font-medium text-amber-100"
                  }
                >
                  {Sync_Health.Health_Ok ? "Synced" : "Not synced"}
                </span>
              ) : null}
            </div>
            <p className="text-xs text-zinc-500">
              {Sync_Health?.Health_Summary
                ? Sync_Health.Health_Summary
                : syncStatus
                  ? `${syncStatus.packages_on_disk} packages on disk · ${syncStatus.imports_recorded} in library` +
                    (syncStatus.pending_import ? ` · ${syncStatus.pending_import} pending import` : "") +
                    (ownerSummary ? ` · ${ownerSummary}` : "")
                  : "Pull Stephen + Chris packages from GitHub and import into this library."}
              {syncStatus?.last_import_at
                ? ` · Last import ${new Date(syncStatus.last_import_at).toLocaleString()}`
                : ""}
            </p>
            {syncStatus?.auto_sync_enabled ? (
              <p className="mt-1 text-xs text-emerald-600/90">
                Video packages auto-sync every {syncStatus.auto_sync_interval_minutes ?? 10} min (API + this page when stale).
              </p>
            ) : null}
            {syncStatus?.brother_auto_pull_enabled ? (
              <p className="mt-1 text-xs text-emerald-600/90">
                Code auto-pull every {syncStatus.brother_auto_pull_interval_minutes ?? 60} min while API runs
                {syncStatus.last_code_pull_at
                  ? ` · last ${new Date(syncStatus.last_code_pull_at).toLocaleString()}`
                  : ""}
                .
              </p>
            ) : null}
            {syncStatus?.git?.commit ? (
              <p className="mt-1 text-xs text-zinc-500">
                Code: {syncStatus.git.branch ?? "branch"} @ {syncStatus.git.commit}
                {syncStatus.git.commits_behind != null && syncStatus.git.commits_behind > 0
                  ? ` · ${syncStatus.git.commits_behind} commit(s) behind remote`
                  : " · up to date with remote code"}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            disabled={syncBusy || backendOnline === false}
            onClick={handleSyncShared}
            className="rounded-xl border border-violet-700 bg-violet-600/20 px-4 py-2 text-sm font-medium text-violet-100 hover:bg-violet-600/30 disabled:opacity-40"
          >
            {syncBusy ? "Syncing…" : "Sync now"}
          </button>
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">Production library</h2>
          <p className="text-sm text-zinc-400">
            Production memory for Cursor — history, components, and versions. Reuse info is advisory unless you ask for unused-only.
          </p>
        </div>
        <div className="flex gap-3">
          <Link
            href="/command"
            className="rounded-xl border border-violet-700 bg-violet-600/20 px-4 py-2 text-sm font-medium text-violet-100"
          >
            Command Cursor
          </Link>
          <label className="cursor-pointer rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800">
            {busy ? "Importing…" : "Import MP4"}
            <input
              type="file"
              accept="video/mp4,video/*"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleUpload(file);
              }}
            />
          </label>
        </div>
      </div>

      {message ? <p className="text-sm text-zinc-300">{message}</p> : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {loading ? (
          <p className="text-sm text-zinc-500">Loading library…</p>
        ) : videos.length === 0 ? (
          <p className="text-sm text-zinc-500">No production videos yet. Run a command or import an MP4.</p>
        ) : (
          videos.map((video) => (
            <Link
              key={video.id}
              href={`/library/${video.id}`}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-4 hover:border-zinc-700"
            >
              {video.final_output_path && productionMediaUrl(video.final_output_path) ? (
                <div className="relative mb-3">
                  <video
                    src={productionMediaUrl(video.final_output_path)!}
                    className="aspect-[9/16] w-full rounded-lg bg-zinc-950 object-cover"
                    muted
                    playsInline
                    preload="metadata"
                  />
                  {video.duration_sec ? (
                    <span className="absolute bottom-2 right-2 rounded bg-black/75 px-2 py-0.5 text-xs text-zinc-100">
                      {formatTimecode(video.duration_sec)}
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="mb-3 flex aspect-[9/16] items-center justify-center rounded-lg bg-zinc-950 text-xs text-zinc-600">
                  No preview
                </div>
              )}
              <p className="font-medium text-zinc-100">
                Video {video.id}
                {video.version && video.version > 1 ? ` ${video.version_label || `v${video.version}`}` : ""}
              </p>
              <p className="truncate text-sm text-zinc-400">{video.title}</p>
              <p className="mt-1 text-xs text-zinc-500">
                {[
                  video.duration_sec ? formatDuration(video.duration_sec) : null,
                  video.speaker,
                  video.topic,
                  (video.metadata as { visual_style?: string } | undefined)?.visual_style,
                  video.status,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
