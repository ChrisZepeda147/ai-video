"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchApprovedVisuals,
  fetchProductionProject,
  fetchSourceMedia,
  getMediaUrl,
  postAcquireSource,
  postBuildTimeline,
  postClipSegment,
  postCreateProject,
  postRenderProject,
  postTranscribeSource,
  productionMediaUrl,
} from "@/lib/api";
import type { ConceptItem, ProductionProjectItem, SourceMediaItem, VisualAssetItem } from "@/lib/types";

const FORMATS = [
  { id: "audio_visuals", label: "Audio + AI Visuals" },
  { id: "source_video_visuals", label: "Source Video + AI Visuals" },
  { id: "original_story", label: "Original Story / Audio" },
] as const;

const CAPTION_PRESETS = [
  { id: "viral_bold", label: "Viral Bold" },
  { id: "clean", label: "Clean" },
  { id: "minimal", label: "Minimal" },
  { id: "story", label: "Story" },
] as const;

type TimelineSegment = {
  type: string;
  start: number;
  end: number;
  motion?: string;
  layout?: string;
};

type Props = {
  initialSourceMediaId?: string;
  initialProjectId?: string;
  selectedConcept?: ConceptItem | null;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onMessage: (msg: string) => void;
};

export function ShortAssemblyPanel({
  initialSourceMediaId = "",
  initialProjectId = "",
  selectedConcept,
  busy,
  setBusy,
  onMessage,
}: Props) {
  const [sourceMediaId, setSourceMediaId] = useState(initialSourceMediaId);
  const [source, setSource] = useState<SourceMediaItem | null>(null);
  const [segmentStart, setSegmentStart] = useState("0");
  const [segmentEnd, setSegmentEnd] = useState("30");
  const [segmentId, setSegmentId] = useState<number | null>(null);
  const [formatProfile, setFormatProfile] = useState<string>("audio_visuals");
  const [captionPreset, setCaptionPreset] = useState("viral_bold");
  const [hookText, setHookText] = useState("");
  const [approvedVisuals, setApprovedVisuals] = useState<VisualAssetItem[]>([]);
  const [selectedVisualIds, setSelectedVisualIds] = useState<number[]>([]);
  const [projectId, setProjectId] = useState<number | null>(
    initialProjectId ? Number(initialProjectId) : null,
  );
  const [project, setProject] = useState<ProductionProjectItem | null>(null);
  const [timelinePreview, setTimelinePreview] = useState<TimelineSegment[]>([]);

  const loadSource = useCallback(async (id: number) => {
    const result = await fetchSourceMedia(id);
    if (result.ok) {
      setSource(result.data.item);
      if (result.data.item.transcript && !hookText) {
        /* keep user hook */
      }
    }
  }, [hookText]);

  const loadProject = useCallback(async (id: number) => {
    const result = await fetchProductionProject(id);
    if (!result.ok) return;
    setProject(result.data);
    setProjectId(result.data.id);
    setFormatProfile(result.data.format_profile);
    setCaptionPreset(result.data.caption_preset || "viral_bold");
    setHookText(result.data.hook_text || "");
    if (result.data.source_media_id) {
      setSourceMediaId(String(result.data.source_media_id));
      await loadSource(result.data.source_media_id);
    }
    if (result.data.timeline_json) {
      try {
        const parsed = JSON.parse(result.data.timeline_json) as { segments?: TimelineSegment[] };
        setTimelinePreview(parsed.segments || []);
      } catch {
        setTimelinePreview([]);
      }
    }
  }, [loadSource]);

  useEffect(() => {
    fetchApprovedVisuals({ limit: 50 }).then((r) => {
      if (r.ok) setApprovedVisuals(r.data.items);
    });
  }, []);

  useEffect(() => {
    if (initialSourceMediaId) {
      const id = Number(initialSourceMediaId);
      if (id) loadSource(id);
    }
  }, [initialSourceMediaId, loadSource]);

  useEffect(() => {
    if (initialProjectId) {
      const id = Number(initialProjectId);
      if (id) loadProject(id);
    }
  }, [initialProjectId, loadProject]);

  useEffect(() => {
    if (selectedConcept?.hook_idea && !hookText) {
      setHookText(selectedConcept.hook_idea);
    }
  }, [selectedConcept, hookText]);

  function toggleVisual(id: number) {
    setSelectedVisualIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function moveVisual(id: number, dir: -1 | 1) {
    setSelectedVisualIds((prev) => {
      const idx = prev.indexOf(id);
      if (idx < 0) return prev;
      const next = [...prev];
      const swap = idx + dir;
      if (swap < 0 || swap >= next.length) return prev;
      [next[idx], next[swap]] = [next[swap], next[idx]];
      return next;
    });
  }

  async function handleAcquire() {
    const id = Number(sourceMediaId);
    if (!id || busy) return;
    setBusy(true);
    const result = await postAcquireSource(id);
    setBusy(false);
    if (!result.ok) {
      onMessage(result.message);
      return;
    }
    onMessage("Source acquired");
    await loadSource(id);
  }

  async function handleClip() {
    const id = Number(sourceMediaId);
    if (!id || busy) return;
    setBusy(true);
    const result = await postClipSegment(id, {
      start_sec: Number(segmentStart),
      end_sec: Number(segmentEnd),
    });
    setBusy(false);
    if (!result.ok) {
      onMessage(result.message);
      return;
    }
    const payload = result.data as { segment_id?: number };
    if (payload.segment_id) setSegmentId(payload.segment_id);
    onMessage(`Segment clipped (${segmentStart}s–${segmentEnd}s)`);
    await loadSource(id);
  }

  async function handleTranscribe() {
    const id = Number(sourceMediaId);
    if (!id || busy) return;
    setBusy(true);
    const result = await postTranscribeSource(id);
    setBusy(false);
    if (!result.ok) {
      onMessage(result.message);
      return;
    }
    onMessage("Transcript ready");
    await loadSource(id);
  }

  async function handleCreateProject() {
    if (busy) return;
    setBusy(true);
    const created = await postCreateProject({
      title: selectedConcept?.title || source?.title || "New Short",
      niche: selectedConcept?.niche,
      reference_id: selectedConcept?.reference_id,
      source_media_id: sourceMediaId ? Number(sourceMediaId) : undefined,
      source_segment_id: segmentId ?? undefined,
      concept_id: selectedConcept?.id,
      format_profile: formatProfile,
      hook_text: hookText || undefined,
      caption_preset: captionPreset,
      origin_type: formatProfile === "original_story" ? "original" : "reference",
    });
    setBusy(false);
    if (!created.ok) {
      onMessage(created.message);
      return;
    }
    setProjectId(created.data.id);
    setProject(created.data);
    onMessage(`Project #${created.data.id} created`);
  }

  async function handleBuildTimeline() {
    if (!projectId || busy) return;
    setBusy(true);
    const result = await postBuildTimeline(projectId, {
      visual_asset_ids: selectedVisualIds.length ? selectedVisualIds : undefined,
      duration_sec: Number(segmentEnd) - Number(segmentStart),
    });
    setBusy(false);
    if (!result.ok) {
      onMessage(result.message);
      return;
    }
    const payload = result.data as { segments?: TimelineSegment[] };
    setTimelinePreview(payload.segments || []);
    onMessage("Timeline built — review preview below");
    await loadProject(projectId);
  }

  async function handleRender() {
    if (!projectId || busy) return;
    setBusy(true);
    const result = await postRenderProject(projectId);
    setBusy(false);
    if (!result.ok) {
      onMessage(result.message);
      return;
    }
    onMessage("Render complete — check Videos or Review");
    await loadProject(projectId);
  }

  const previewUrl = productionMediaUrl(project?.output_path);

  return (
    <section className="mb-6 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
      <h2 className="text-sm font-semibold text-emerald-200">Short assembly</h2>
      <p className="mt-1 text-xs text-zinc-500">
        Source → segment → transcript → approved visuals → timeline → render 9:16 Short.
      </p>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">Source</h3>
          <div className="flex flex-wrap gap-2">
            <input
              placeholder="Source media ID"
              value={sourceMediaId}
              onChange={(e) => setSourceMediaId(e.target.value)}
              className="w-28 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm"
            />
            <button type="button" disabled={busy || !sourceMediaId} onClick={handleAcquire} className="rounded border border-zinc-700 px-2 py-1 text-xs disabled:opacity-50">
              Acquire
            </button>
            <button type="button" disabled={busy || !sourceMediaId} onClick={() => loadSource(Number(sourceMediaId))} className="rounded border border-zinc-700 px-2 py-1 text-xs disabled:opacity-50">
              Refresh
            </button>
          </div>
          {source ? (
            <div className="text-xs text-zinc-400">
              <p className="font-medium text-zinc-200">{source.title}</p>
              <p className="mt-1">
                Mode: {source.source_mode} · Download: {source.download_status || "pending"}
              </p>
              {source.download_path ? <p className="truncate text-zinc-600">{source.download_path}</p> : null}
            </div>
          ) : null}
        </div>

        <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">Segment</h3>
          <div className="flex flex-wrap gap-2">
            <input value={segmentStart} onChange={(e) => setSegmentStart(e.target.value)} placeholder="Start" className="w-20 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm" />
            <input value={segmentEnd} onChange={(e) => setSegmentEnd(e.target.value)} placeholder="End" className="w-20 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm" />
            <button type="button" disabled={busy || !sourceMediaId} onClick={handleClip} className="rounded border border-zinc-700 px-2 py-1 text-xs disabled:opacity-50">
              Clip
            </button>
            <button type="button" disabled={busy || !sourceMediaId} onClick={handleTranscribe} className="rounded border border-zinc-700 px-2 py-1 text-xs disabled:opacity-50">
              Transcribe
            </button>
          </div>
        </div>
      </div>

      {source?.transcript ? (
        <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">Transcript</h3>
          <p className="mt-2 max-h-32 overflow-y-auto text-sm text-zinc-300">{source.transcript}</p>
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <label className="text-xs text-zinc-400">
          Format
          <select value={formatProfile} onChange={(e) => setFormatProfile(e.target.value)} className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-100">
            {FORMATS.map((f) => (
              <option key={f.id} value={f.id}>{f.label}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-zinc-400">
          Captions
          <select value={captionPreset} onChange={(e) => setCaptionPreset(e.target.value)} className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-100">
            {CAPTION_PRESETS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-zinc-400">
          Hook (optional)
          <input value={hookText} onChange={(e) => setHookText(e.target.value)} placeholder="THIS IS WHY MOST PEOPLE FAIL" className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-100" />
        </label>
      </div>

      <div className="mt-4">
        <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">Approved visuals</h3>
        {approvedVisuals.length === 0 ? (
          <p className="mt-2 text-xs text-zinc-600">No approved visuals yet — import generation jobs and approve in Review.</p>
        ) : (
          <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {approvedVisuals.map((v) => {
              const selected = selectedVisualIds.includes(v.id);
              const url = getMediaUrl(v.media_url);
              return (
                <li key={v.id} className={`rounded border p-2 ${selected ? "border-emerald-500/50 bg-emerald-500/5" : "border-zinc-800"}`}>
                  <div className="flex items-center gap-2">
                    <input type="checkbox" checked={selected} onChange={() => toggleVisual(v.id)} />
                    <span className="text-xs text-zinc-300">#{v.id} · {v.asset_type}</span>
                    {selected ? (
                      <span className="ml-auto flex gap-1">
                        <button type="button" onClick={() => moveVisual(v.id, -1)} className="text-xs text-zinc-500">↑</button>
                        <button type="button" onClick={() => moveVisual(v.id, 1)} className="text-xs text-zinc-500">↓</button>
                      </span>
                    ) : null}
                  </div>
                  {url && v.asset_type === "image" ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={url} alt="" className="mt-2 aspect-[9/16] w-full rounded object-cover" />
                  ) : url ? (
                    <video src={url} className="mt-2 aspect-[9/16] w-full rounded object-cover" muted />
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={handleCreateProject} className="rounded bg-emerald-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">
          Create Project
        </button>
        <button type="button" disabled={busy || !projectId} onClick={handleBuildTimeline} className="rounded border border-zinc-700 px-3 py-1.5 text-xs disabled:opacity-50">
          Build Timeline
        </button>
        <button type="button" disabled={busy || !projectId} onClick={handleRender} className="rounded bg-violet-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">
          Render Short
        </button>
        {projectId ? <span className="self-center text-xs text-zinc-500">Project #{projectId} · {project?.status || "draft"}</span> : null}
      </div>

      {timelinePreview.length > 0 ? (
        <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">Timeline preview</h3>
          <ul className="mt-2 space-y-1 font-mono text-xs text-zinc-400">
            {timelinePreview.map((seg, i) => (
              <li key={i}>
                {seg.start.toFixed(1)}–{seg.end.toFixed(1)}s · {seg.type}
                {seg.motion ? ` · ${seg.motion}` : ""}
                {seg.layout ? ` · ${seg.layout}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {previewUrl ? (
        <div className="mt-4">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">Latest render</h3>
          <video src={previewUrl} controls className="mt-2 max-w-[220px] rounded-lg" />
        </div>
      ) : null}
    </section>
  );
}
