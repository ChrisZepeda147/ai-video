"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CommandWorkspace } from "@/components/command/command-workspace";
import { LibraryTrimEditor } from "@/components/library/library-trim-editor";
import { PostingStatusEditor } from "@/components/library/posting-status-editor";
import { FinishedBucketBadge } from "@/components/library/finished-bucket-filter";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  CollapsibleMediaSection,
  MediaPreviewCard,
  type MediaPreviewItem,
} from "@/components/shared/media-preview-card";
import {
  fetchHealth,
  fetchLibrarySpeakers,
  fetchProductionVideo,
  postUpdateVideoSpeaker,
  productionMediaUrl,
} from "@/lib/api";
import { displayMediaPath } from "@/lib/format";
import type { ProductionLibraryVideo, ProductionVideoComponent } from "@/lib/types";

function componentSections(components: ProductionVideoComponent[]) {
  const audio: MediaPreviewItem[] = [];
  const video: MediaPreviewItem[] = [];
  const other: MediaPreviewItem[] = [];
  for (const comp of components) {
    const kind = comp.media_kind || comp.component_type;
    const item: MediaPreviewItem = { ...comp, id: comp.id };
    if (kind === "audio" || comp.component_type === "audio" || comp.component_type === "caption") {
      audio.push(item);
    } else if (
      kind === "video" ||
      comp.component_type === "visual" ||
      comp.component_type === "final"
    ) {
      video.push(item);
    } else {
      other.push(item);
    }
  }
  return { audio, video, other };
}

function searchIntent(video: ProductionLibraryVideo): string | null {
  const meta = video.metadata;
  if (!meta || typeof meta !== "object") return null;
  const intent = meta.search_intent;
  return typeof intent === "string" && intent.trim() ? intent.trim() : null;
}

export function VideoDetailWorkspace({ videoId }: { videoId: number }) {
  const router = useRouter();
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
      <BackendOfflineBanner message="From repo root run npm run dev, then refresh." />
    ) : (
      <p className="text-sm text-zinc-500">Video not found.</p>
    );
  }

  const intent = searchIntent(video);
  const sections = componentSections(video.components ?? []);
  const finalPath = displayMediaPath(video.final_output_path);

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
        <div className="mt-2">
          <FinishedBucketBadge used={Boolean(video.used ?? video.posting_status?.posted)} />
        </div>
        {finalPath ? (
          <p className="mt-1 break-all font-mono text-xs text-violet-300/90">{finalPath}</p>
        ) : null}
      </div>

      <section className="max-w-xl rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
        <PostingStatusEditor
          videoId={video.id}
          status={video.posting_status}
          onUpdated={(updated) => setVideo(updated)}
        />
        {(video.posting_status?.linked?.length ?? 0) > 0 ? (
          <ul className="mt-3 space-y-1 border-t border-zinc-800/80 pt-3 text-xs text-zinc-400">
            {video.posting_status?.linked.map((link) => (
              <li key={link.job_id}>
                {link.account_owner ? `${link.account_owner} · ` : ""}
                Linked {link.platform}
                {link.platform_url ? (
                  <>
                    {" · "}
                    <a href={link.platform_url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                      View post
                    </a>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

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
        <div className="max-w-xl space-y-4">
          <video
            src={productionMediaUrl(video.final_output_path) ?? undefined}
            controls
            className="aspect-[9/16] w-full max-w-[280px] rounded-xl bg-zinc-950"
          />
          {productionMediaUrl(video.final_output_path) ? (
            <a
              href={productionMediaUrl(video.final_output_path)!}
              target="_blank"
              rel="noreferrer"
              className="inline-block text-sm text-violet-300 hover:underline"
            >
              Open final render
            </a>
          ) : null}
          <LibraryTrimEditor
            video={video}
            onSaved={(next, mode) => {
              if (mode === "new_version" && next.id !== video.id) {
                router.push(`/library/${next.id}`);
                return;
              }
              setVideo(next);
            }}
          />
        </div>
      ) : null}

      <section className="max-w-3xl">
        <h2 className="mb-4 text-lg font-semibold text-zinc-100">Command Cursor</h2>
        <CommandWorkspace
          videoId={video.id}
          placeholder="Replace scene 4. Use the same audio but cars only."
        />
      </section>

      <section className="space-y-4">
        <CollapsibleMediaSection title="Audio" count={sections.audio.length}>
          <ul className="space-y-2">
            {sections.audio.length === 0 ? (
              <li className="text-xs text-zinc-500">No audio components</li>
            ) : (
              sections.audio.map((item) => <MediaPreviewCard key={item.id} item={item} />)
            )}
          </ul>
        </CollapsibleMediaSection>

        <CollapsibleMediaSection title="Video / visuals" count={sections.video.length}>
          <ul className="space-y-2">
            {sections.video.length === 0 ? (
              <li className="text-xs text-zinc-500">No video components</li>
            ) : (
              sections.video.map((item) => <MediaPreviewCard key={item.id} item={item} />)
            )}
          </ul>
        </CollapsibleMediaSection>

        {sections.other.length > 0 ? (
          <CollapsibleMediaSection title="Other" count={sections.other.length} defaultOpen={false}>
            <ul className="space-y-2">
              {sections.other.map((item) => (
                <MediaPreviewCard key={item.id} item={item} />
              ))}
            </ul>
          </CollapsibleMediaSection>
        ) : null}
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
