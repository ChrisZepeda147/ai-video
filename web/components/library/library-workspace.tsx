"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import { fetchHealth, fetchProductionLibrary, postImportProductionVideo, productionMediaUrl } from "@/lib/api";
import type { ProductionLibraryVideo } from "@/lib/types";

export function LibraryWorkspace() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [videos, setVideos] = useState<ProductionLibraryVideo[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const health = await fetchHealth();
    setBackendOnline(health.ok);
    if (!health.ok) return;
    const result = await fetchProductionLibrary({ limit: 200 });
    if (result.ok) setVideos(result.data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
        {videos.length === 0 ? (
          <p className="text-sm text-zinc-500">No production videos yet. Run a command or import an MP4.</p>
        ) : (
          videos.map((video) => (
            <Link
              key={video.id}
              href={`/library/${video.id}`}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-4 hover:border-zinc-700"
            >
              {video.final_output_path ? (
                <video
                  src={productionMediaUrl(video.final_output_path) ?? undefined}
                  className="mb-3 aspect-[9/16] w-full rounded-lg bg-zinc-950 object-cover"
                  muted
                  playsInline
                  preload="metadata"
                />
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
