"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { postTrimLibraryVideo, productionMediaUrl } from "@/lib/api";
import { formatDuration, formatTimecode } from "@/lib/format";
import type { ProductionLibraryVideo } from "@/lib/types";

type TrimMode = "override" | "new_version";

function parseSec(raw: string, fallback: number): number {
  const value = parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function LibraryTrimEditor({
  video,
  onSaved,
}: {
  video: ProductionLibraryVideo;
  onSaved: (next: ProductionLibraryVideo, mode: TrimMode) => void;
}) {
  const mediaRef = useRef<HTMLVideoElement>(null);
  const duration = video.duration_sec ?? 0;
  const [startSec, setStartSec] = useState("0");
  const [endSec, setEndSec] = useState(duration > 0 ? String(duration) : "");
  const [mode, setMode] = useState<TrimMode>("new_version");
  const [changeSummary, setChangeSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setEndSec(duration > 0 ? String(duration) : "");
  }, [duration, video.id]);

  const start = parseSec(startSec, 0);
  const end = parseSec(endSec, duration);
  const span = Math.max(0, end - start);
  const mediaSrc = video.final_output_path ? productionMediaUrl(video.final_output_path) : null;

  const setInFromPlayer = useCallback(() => {
    const t = mediaRef.current?.currentTime ?? 0;
    setStartSec(t.toFixed(2));
  }, []);

  const setOutFromPlayer = useCallback(() => {
    const t = mediaRef.current?.currentTime ?? duration;
    setEndSec(t.toFixed(2));
  }, [duration]);

  async function handleTrim() {
    if (busy || !mediaSrc) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const result = await postTrimLibraryVideo(video.id, {
      start_sec: start,
      end_sec: end,
      mode,
      change_summary: changeSummary.trim() || undefined,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setMessage(
      mode === "override"
        ? "Trim saved — this video was updated in place."
        : `New version saved — Video ${result.data.id}.`,
    );
    onSaved(result.data, mode);
  }

  if (!mediaSrc) {
    return <p className="text-sm text-zinc-500">No final render available to trim.</p>;
  }

  return (
    <div className="space-y-4 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div>
        <h2 className="text-sm font-semibold text-zinc-100">Trim clip</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Set in/out points, preview, then replace this file or save a new library version.
        </p>
      </div>

      <video
        ref={mediaRef}
        src={mediaSrc}
        controls
        className="aspect-[9/16] w-full max-w-[240px] rounded-xl bg-zinc-950"
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-zinc-400">
          Start (sec)
          <input
            type="number"
            min={0}
            step={0.01}
            value={startSec}
            onChange={(e) => setStartSec(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
        </label>
        <label className="block text-xs text-zinc-400">
          End (sec)
          <input
            type="number"
            min={0}
            step={0.01}
            value={endSec}
            onChange={(e) => setEndSec(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={setInFromPlayer}
          className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800"
        >
          Set start from playhead
        </button>
        <button
          type="button"
          onClick={setOutFromPlayer}
          className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800"
        >
          Set end from playhead
        </button>
      </div>

      <p className="text-xs text-zinc-500">
        Output length: {formatDuration(span)} ({formatTimecode(span)})
        {duration > 0 ? ` · source ${formatTimecode(duration)}` : ""}
      </p>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-zinc-400">Save as</legend>
        <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-zinc-800 px-3 py-2 text-sm">
          <input
            type="radio"
            name={`trim-mode-${video.id}`}
            checked={mode === "new_version"}
            onChange={() => setMode("new_version")}
            className="mt-1"
          />
          <span>
            <span className="text-zinc-100">New version</span>
            <span className="mt-0.5 block text-xs text-zinc-500">Keeps original — adds child version in library</span>
          </span>
        </label>
        <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-amber-900/40 px-3 py-2 text-sm">
          <input
            type="radio"
            name={`trim-mode-${video.id}`}
            checked={mode === "override"}
            onChange={() => setMode("override")}
            className="mt-1"
          />
          <span>
            <span className="text-amber-100">Replace this video</span>
            <span className="mt-0.5 block text-xs text-zinc-500">Overwrites final.mp4 on this library entry</span>
          </span>
        </label>
      </fieldset>

      <label className="block text-xs text-zinc-400">
        Note (optional)
        <input
          type="text"
          value={changeSummary}
          onChange={(e) => setChangeSummary(e.target.value)}
          placeholder="Trim cold open"
          className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
        />
      </label>

      <button
        type="button"
        disabled={busy || span <= 0}
        onClick={() => void handleTrim()}
        className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-40"
      >
        {busy ? "Trimming…" : mode === "override" ? "Trim and replace" : "Trim and save new version"}
      </button>

      {error ? <p className="text-xs text-red-300">{error}</p> : null}
      {message ? <p className="text-xs text-emerald-300">{message}</p> : null}
    </div>
  );
}
