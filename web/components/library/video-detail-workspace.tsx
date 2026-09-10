"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CommandWorkspace } from "@/components/command/command-workspace";
import { BackendOfflineBanner } from "@/components/backend-banner";
import { fetchHealth, fetchProductionVideo, productionMediaUrl } from "@/lib/api";
import type { ProductionLibraryVideo } from "@/lib/types";

export function VideoDetailWorkspace({ videoId }: { videoId: number }) {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [video, setVideo] = useState<ProductionLibraryVideo | null>(null);

  const load = useCallback(async () => {
    const health = await fetchHealth();
    setBackendOnline(health.ok);
    if (!health.ok) return;
    const result = await fetchProductionVideo(videoId);
    if (result.ok) setVideo(result.data);
  }, [videoId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!video && backendOnline !== false) {
    return <p className="text-sm text-zinc-500">Loading…</p>;
  }

  if (!video) {
    return backendOnline === false ? (
      <BackendOfflineBanner message="Start the API, then refresh." />
    ) : (
      <p className="text-sm text-zinc-500">Video not found.</p>
    );
  }

  const grouped = (video.components ?? []).reduce<Record<string, typeof video.components>>((acc, comp) => {
    const key = comp.component_type || "other";
    acc[key] = acc[key] || [];
    acc[key].push(comp);
    return acc;
  }, {});

  return (
    <div className="space-y-8">
      <div>
        <Link href="/library" className="text-sm text-violet-300 hover:underline">
          ← Library
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-zinc-100">
          Video {video.id} — {video.title}
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          {[video.video_key, video.speaker, video.topic, video.status, video.version_label]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      {video.final_output_path ? (
        <video
          src={productionMediaUrl(video.final_output_path) ?? undefined}
          controls
          className="aspect-[9/16] w-full max-w-[280px] rounded-xl bg-zinc-950"
        />
      ) : null}

      <section className="max-w-3xl">
        <h2 className="mb-4 text-lg font-semibold text-zinc-100">Edit this video</h2>
        <CommandWorkspace
          videoId={video.id}
          placeholder="Replace scene 4. Use the same audio but cars only."
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        {Object.entries(grouped).map(([type, items]) => (
          <div key={type} className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">{type}</h3>
            <ul className="mt-3 space-y-2 text-sm text-zinc-300">
              {(items ?? []).map((item) => (
                <li key={item.id} className="rounded-lg bg-zinc-950 px-3 py-2">
                  <p>{item.label || item.local_path || item.url || "text segment"}</p>
                  {item.text_content ? (
                    <p className="mt-1 line-clamp-4 text-xs text-zinc-500">{item.text_content}</p>
                  ) : null}
                  {item.local_path ? (
                    <a
                      href={productionMediaUrl(item.local_path) ?? undefined}
                      className="mt-1 inline-block text-xs text-violet-300 hover:underline"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open file
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      {video.versions && video.versions.length > 1 ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/30 p-4">
          <h3 className="text-sm font-semibold text-zinc-200">Versions</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {video.versions.map((v) => (
              <li key={v.id}>
                <Link href={`/library/${v.id}`} className="text-violet-300 hover:underline">
                  Video {v.id} {v.version_label || ""} — {v.status}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
