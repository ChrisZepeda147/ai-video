"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CommandWorkspace } from "@/components/command/command-workspace";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  fetchHealth,
  fetchLibrarySpeakers,
  fetchProductionVideo,
  postUpdateVideoSpeaker,
  productionMediaUrl,
} from "@/lib/api";
import type { ProductionLibraryVideo } from "@/lib/types";

function searchIntent(video: ProductionLibraryVideo): string | null {
  const meta = video.metadata;
  if (!meta || typeof meta !== "object") return null;
  const intent = meta.search_intent;
  return typeof intent === "string" && intent.trim() ? intent.trim() : null;
}

export function VideoDetailWorkspace({ videoId }: { videoId: number }) {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [video, setVideo] = useState<ProductionLibraryVideo | null>(null);
  const [speakerOptions, setSpeakerOptions] = useState<string[]>([]);
  const [editSpeaker, setEditSpeaker] = useState(false);
  const [speakerDraft, setSpeakerDraft] = useState("");
  const [rememberSpeaker, setRememberSpeaker] = useState(true);
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [speakerMessage, setSpeakerMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const health = await fetchHealth();
    setBackendOnline(health.ok);
    if (!health.ok) return;
    const [videoResult, speakersResult] = await Promise.all([
      fetchProductionVideo(videoId),
      fetchLibrarySpeakers(),
    ]);
    if (videoResult.ok) {
      setVideo(videoResult.data);
      setSpeakerDraft(videoResult.data.speaker || "");
    }
    if (speakersResult.ok) setSpeakerOptions(speakersResult.data.items);
  }, [videoId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSaveSpeaker() {
    if (!speakerDraft.trim() || speakerBusy) return;
    setSpeakerBusy(true);
    setSpeakerMessage(null);
    const result = await postUpdateVideoSpeaker(videoId, {
      speaker: speakerDraft.trim(),
      remember_correction: rememberSpeaker,
    });
    setSpeakerBusy(false);
    if (!result.ok) {
      setSpeakerMessage(result.message);
      return;
    }
    setVideo(result.data);
    setEditSpeaker(false);
    setSpeakerMessage(
      rememberSpeaker
        ? `Speaker saved as ${speakerDraft.trim()} — remembered for this YouTube source.`
        : `Speaker saved as ${speakerDraft.trim()}.`,
    );
  }

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

  const intent = searchIntent(video);
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
          {[video.video_key, video.topic, video.status, video.version_label].filter(Boolean).join(" · ")}
        </p>
      </div>

      <section className="max-w-xl rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Speaker</h2>
            {!editSpeaker ? (
              <p className="mt-1 text-sm text-zinc-300">{video.speaker || "Unknown"}</p>
            ) : (
              <div className="mt-2 space-y-2">
                <input
                  list="speaker-suggestions"
                  value={speakerDraft}
                  onChange={(e) => setSpeakerDraft(e.target.value)}
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                  placeholder="Jocko Willink"
                />
                <datalist id="speaker-suggestions">
                  {speakerOptions.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
                <label className="flex items-center gap-2 text-xs text-zinc-400">
                  <input
                    type="checkbox"
                    checked={rememberSpeaker}
                    onChange={(e) => setRememberSpeaker(e.target.checked)}
                  />
                  Remember for this YouTube source (future jobs auto-use this name)
                </label>
              </div>
            )}
            {intent && intent.toLowerCase() !== (video.speaker || "").toLowerCase() ? (
              <p className="mt-2 text-xs text-amber-300/90">
                Searched for: {intent} · Catalog speaker: {video.speaker || "Unknown"}
              </p>
            ) : null}
            {speakerMessage ? <p className="mt-2 text-xs text-zinc-400">{speakerMessage}</p> : null}
          </div>
          {!editSpeaker ? (
            <button
              type="button"
              onClick={() => {
                setSpeakerDraft(video.speaker || "");
                setEditSpeaker(true);
                setSpeakerMessage(null);
              }}
              className="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-800"
            >
              Edit speaker
            </button>
          ) : (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={speakerBusy || !speakerDraft.trim()}
                onClick={() => void handleSaveSpeaker()}
                className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
              >
                {speakerBusy ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => setEditSpeaker(false)}
                className="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </section>

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
