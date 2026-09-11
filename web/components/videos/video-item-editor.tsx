"use client";

import { useState, type MouseEvent } from "react";
import { postUpdateVideoLibraryItem } from "@/lib/api";
import {
  formatMediaKind,
  normalizeVideoMediaKind,
  type VideoMediaKind,
} from "@/lib/format";
import type { VideoLibraryItem } from "@/lib/types";

const MEDIA_KIND_OPTIONS: VideoMediaKind[] = ["video", "video_audio", "audio"];

export function VideoItemEditor({
  item,
  speakerOptions,
  busy,
  onBusy,
  onSaved,
  onCancel,
}: {
  item: VideoLibraryItem;
  speakerOptions: string[];
  busy: boolean;
  onBusy: (v: boolean) => void;
  onSaved: (updated: VideoLibraryItem) => void;
  onCancel: () => void;
}) {
  const [speaker, setSpeaker] = useState(item.speaker || item.title || "");
  const [mediaKind, setMediaKind] = useState<VideoMediaKind>(
    normalizeVideoMediaKind(item.media_kind),
  );
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function handleSave(e: MouseEvent) {
    e.stopPropagation();
    if (busy || !speaker.trim()) return;
    onBusy(true);
    setError(null);
    const result = await postUpdateVideoLibraryItem({
      source: item.source,
      library_id: item.library_id ?? undefined,
      project_id: item.project_id ?? undefined,
      legacy_id: item.legacy_id ?? undefined,
      speaker: speaker.trim(),
      media_kind: mediaKind,
      remember_speaker: remember && item.source === "library",
    });
    onBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    onSaved(result.data.item);
  }

  return (
    <div
      className="mt-3 rounded-lg border border-violet-800/50 bg-violet-950/20 p-3"
      onClick={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-violet-300">Edit</p>
      <label className="mt-2 block text-xs text-zinc-400">
        Speaker / title
        <input
          list={`speaker-suggestions-${item.key}`}
          value={speaker}
          onChange={(e) => setSpeaker(e.target.value)}
          className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
        />
        <datalist id={`speaker-suggestions-${item.key}`}>
          {speakerOptions.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </label>
      <label className="mt-2 block text-xs text-zinc-400">
        Category
        <select
          value={mediaKind}
          onChange={(e) => setMediaKind(e.target.value as VideoMediaKind)}
          className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
        >
          {MEDIA_KIND_OPTIONS.map((kind) => (
            <option key={kind} value={kind}>
              {formatMediaKind(kind)}
            </option>
          ))}
        </select>
      </label>
      {item.source === "library" ? (
        <label className="mt-2 flex items-center gap-2 text-xs text-zinc-500">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember speaker for this YouTube source
        </label>
      ) : null}
      {error ? <p className="mt-2 text-xs text-red-400">{error}</p> : null}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={busy || !speaker.trim()}
          onClick={(e) => void handleSave(e)}
          className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          Save
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onCancel();
          }}
          className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
