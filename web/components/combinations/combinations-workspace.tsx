"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  fetchCombinationCatalog,
  fetchCombinationStatus,
  postCombinationRender,
  postSyncCombinationCatalog,
  productionMediaUrl,
} from "@/lib/api";
import { displayMediaPath, formatDuration, formatTimecode } from "@/lib/format";
import type {
  CombinationCatalog,
  CombinationStatusResponse,
  CombinationVisualStatus,
} from "@/lib/types";

type Owner = "chris" | "stephen";

function statusClasses(status: CombinationVisualStatus["status"]) {
  if (status === "available") return "border-emerald-800 bg-emerald-950/40 text-emerald-200";
  if (status === "used_by_selected_owner") return "border-red-800 bg-red-950/40 text-red-200";
  return "border-amber-800 bg-amber-950/40 text-amber-200";
}

function statusLabel(item: CombinationVisualStatus, owner: Owner) {
  if (item.status === "available") return "Available";
  if (item.status === "used_by_selected_owner") return `Used by ${owner}`;
  return `Used by ${item.other_owner || "other owner"}`;
}

export function CombinationsWorkspace() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [owner, setOwner] = useState<Owner>("chris");
  const [catalog, setCatalog] = useState<CombinationCatalog | null>(null);
  const [selectedSpeaker, setSelectedSpeaker] = useState<string | null>(null);
  const [selectedAudioId, setSelectedAudioId] = useState<number | null>(null);
  const [selectedPackId, setSelectedPackId] = useState<number | null>(null);
  const [pairing, setPairing] = useState<CombinationStatusResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [forceRender, setForceRender] = useState(false);
  const [trimStart, setTrimStart] = useState("");
  const [trimEnd, setTrimEnd] = useState("");
  const [selectedVisualCategory, setSelectedVisualCategory] = useState<string | null>(null);

  const loadCatalog = useCallback(async (opts?: { prune?: boolean }) => {
    if (opts?.prune) {
      await postSyncCombinationCatalog({ prune_missing: true });
    }
    const result = await fetchCombinationCatalog(owner, opts?.prune);
    if (result.ok) {
      setBackendOnline(true);
      setCatalog(result.data);
    } else {
      setBackendOnline(result.error === "offline" ? false : true);
    }
  }, [owner]);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  const speakers = useMemo(
    () => Object.keys(catalog?.audio_by_speaker ?? {}).sort(),
    [catalog],
  );

  const visualCategories = useMemo(() => {
    const grouped = catalog?.visual_by_category;
    if (grouped && Object.keys(grouped).length > 0) {
      return Object.keys(grouped).sort();
    }
    const cats = new Set((catalog?.visual_packs ?? []).map((p) => p.category || "Custom"));
    return Array.from(cats).sort();
  }, [catalog]);

  const visualItems = useMemo(() => {
    if (!catalog) return [];
    if (selectedVisualCategory && catalog.visual_by_category?.[selectedVisualCategory]) {
      return catalog.visual_by_category[selectedVisualCategory];
    }
    if (selectedVisualCategory) {
      return catalog.visual_packs.filter((p) => (p.category || "Custom") === selectedVisualCategory);
    }
    return catalog.visual_packs;
  }, [catalog, selectedVisualCategory]);

  const pairingByPackId = useMemo(() => {
    const map = new Map<number, CombinationVisualStatus>();
    for (const item of pairing?.visuals ?? []) {
      map.set(item.visual_pack_id, item);
    }
    return map;
  }, [pairing]);

  const audioItems = useMemo(() => {
    if (!catalog) return [];
    if (selectedSpeaker) return catalog.audio_by_speaker[selectedSpeaker] ?? [];
    return Object.values(catalog.audio_by_speaker).flat();
  }, [catalog, selectedSpeaker]);

  const selectedAudio = audioItems.find((a) => a.component_id === selectedAudioId) ?? null;
  const selectedPack = catalog?.visual_packs.find((p) => p.id === selectedPackId) ?? null;
  const selectedPairing = pairing?.visuals.find((v) => v.visual_pack_id === selectedPackId);
  const audioDurationSec =
    pairing?.audio.duration_sec ?? selectedAudio?.duration_sec ?? null;
  const visualDurationSec =
    selectedPairing?.duration_sec ?? selectedPack?.duration_sec ?? null;
  const trimStartSec = trimStart ? parseFloat(trimStart) : 0;
  const trimEndSec = trimEnd ? parseFloat(trimEnd) : audioDurationSec ?? 0;
  const outputDurationSec =
    audioDurationSec != null
      ? Math.max(0, (trimEnd ? trimEndSec : audioDurationSec) - trimStartSec)
      : null;

  useEffect(() => {
    if (!selectedAudio?.duration_sec) {
      setTrimStart("");
      setTrimEnd("");
      return;
    }
    setTrimStart("0");
    setTrimEnd(String(Math.round(selectedAudio.duration_sec * 100) / 100));
  }, [selectedAudio?.component_id, selectedAudio?.duration_sec]);

  useEffect(() => {
    if (!selectedAudioId) {
      setPairing(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const result = await fetchCombinationStatus({ owner, audio_component_id: selectedAudioId });
      if (!cancelled && result.ok) setPairing(result.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [owner, selectedAudioId]);

  async function handleRender() {
    if (!selectedAudioId || !selectedPackId) return;
    if (selectedPairing?.used_by_selected_owner && !forceRender) {
      setMessage("This exact pairing was already used for this owner. Check “Use anyway” to render.");
      return;
    }
    setBusy(true);
    setMessage(null);
    const startSec = trimStart ? parseFloat(trimStart) : 0;
    const endSec = trimEnd ? parseFloat(trimEnd) : audioDurationSec ?? undefined;
    const result = await postCombinationRender({
      owner,
      audio_component_id: selectedAudioId,
      visual_pack_id: selectedPackId,
      force: forceRender,
      audio_start_sec: startSec,
      audio_end_sec: endSec,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Rendered Video ${result.data.video.id} — ${result.data.output_path}`);
    const status = await fetchCombinationStatus({ owner, audio_component_id: selectedAudioId });
    if (status.ok) setPairing(status.data);
    await loadCatalog();
  }

  if (backendOnline === false) {
    return <BackendOfflineBanner message="From repo root run npm run dev, then refresh." />;
  }

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
        <p className="text-sm text-zinc-400">
          Combine reusable audio + visual packs. Pairing memory is per owner — same combo can be green for Stephen
          after Chris used it (yellow warning).
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Owner</span>
          {(["chris", "stephen"] as Owner[]).map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setOwner(name)}
              className={`rounded-xl px-4 py-2 text-sm font-medium capitalize ${
                owner === name
                  ? "bg-violet-600 text-white"
                  : "border border-zinc-700 text-zinc-300 hover:bg-zinc-800"
              }`}
            >
              {name}
            </button>
          ))}
          <span className="text-xs text-zinc-500">
            {catalog?.audio_count ?? 0} audio · {catalog?.visual_pack_count ?? 0} visual packs
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void loadCatalog({ prune: true }).finally(() => setBusy(false));
              setMessage("Synced catalog and removed missing files.");
            }}
            className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
          >
            Sync &amp; prune missing
          </button>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="text-lg font-semibold text-zinc-100">Audio</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setSelectedSpeaker(null)}
              className={`rounded-lg px-3 py-1 text-xs ${!selectedSpeaker ? "bg-zinc-700" : "border border-zinc-800"}`}
            >
              All
            </button>
            {speakers.map((speaker) => (
              <button
                key={speaker}
                type="button"
                onClick={() => setSelectedSpeaker(speaker)}
                className={`rounded-lg px-3 py-1 text-xs ${
                  selectedSpeaker === speaker ? "bg-zinc-700" : "border border-zinc-800"
                }`}
              >
                {speaker}
              </button>
            ))}
          </div>
          <ul className="mt-4 max-h-[420px] space-y-2 overflow-y-auto">
            {audioItems.map((item) => (
              <li key={item.component_id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedAudioId(item.component_id);
                    setSelectedPackId(null);
                  }}
                  className={`w-full rounded-xl border px-3 py-3 text-left text-sm ${
                    selectedAudioId === item.component_id
                      ? "border-violet-500 bg-violet-500/10"
                      : "border-zinc-800 bg-zinc-950 hover:border-zinc-700"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-violet-300">{item.display_id}</span>
                    {item.duration_sec ? (
                      <span className="text-xs text-zinc-400" title={formatTimecode(item.duration_sec)}>
                        {formatDuration(item.duration_sec)}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 font-medium text-zinc-100">{item.speaker}</p>
                  {(item.display_path || item.local_path) ? (
                    <p className="mt-1 break-all font-mono text-[11px] text-violet-300/90">
                      {item.display_path || displayMediaPath(item.local_path)}
                    </p>
                  ) : null}
                  <p className="line-clamp-2 text-xs text-zinc-500">{item.transcript_excerpt || item.video_title}</p>
                  <Link
                    href={`/library/${item.video_id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="mt-1 inline-block text-[11px] text-violet-400 hover:underline"
                  >
                    Video {item.video_id} in library
                  </Link>
                  {item.local_path ? (
                    <div className="mt-2 space-y-1" onClick={(e) => e.stopPropagation()}>
                      <audio
                        controls
                        preload="metadata"
                        className="h-8 w-full"
                        src={productionMediaUrl(item.local_path) ?? undefined}
                      />
                      {item.duration_sec ? (
                        <p className="text-[11px] text-zinc-500">
                          Length: {formatDuration(item.duration_sec)} ({formatTimecode(item.duration_sec)})
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="text-lg font-semibold text-zinc-100">Visual packs (video)</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setSelectedVisualCategory(null)}
              className={`rounded-lg px-3 py-1 text-xs ${!selectedVisualCategory ? "bg-zinc-700" : "border border-zinc-800"}`}
            >
              All
            </button>
            {visualCategories.map((category) => (
              <button
                key={category}
                type="button"
                onClick={() => setSelectedVisualCategory(category)}
                className={`rounded-lg px-3 py-1 text-xs ${
                  selectedVisualCategory === category ? "bg-zinc-700" : "border border-zinc-800"
                }`}
              >
                {category}
              </button>
            ))}
          </div>
          {!selectedAudioId ? (
            <p className="mt-3 text-sm text-zinc-500">Select audio to see pairing colors (green/yellow/red).</p>
          ) : null}
          {visualItems.length === 0 ? (
            <p className="mt-3 text-sm text-zinc-500">No visual packs — run Sync &amp; prune or render a montage job.</p>
          ) : (
            <ul className="mt-4 max-h-[420px] space-y-2 overflow-y-auto">
              {visualItems.map((pack) => {
                const visual = pairingByPackId.get(pack.id);
                const packId = pack.id;
                const status = visual?.status ?? "available";
                return (
                  <li key={packId}>
                    <button
                      type="button"
                      onClick={() => setSelectedPackId(packId)}
                      className={`w-full rounded-xl border px-3 py-3 text-left text-sm ${statusClasses(status)} ${
                        selectedPackId === packId ? "ring-2 ring-violet-500" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono">{pack.display_id || pack.id}</span>
                        <span className="text-xs">
                          {visual && selectedAudioId ? statusLabel(visual, owner) : pack.category}
                        </span>
                      </div>
                      <p className="mt-1 font-medium">{pack.label}</p>
                      {(pack.display_path || pack.preview_clip_path || pack.clips_root_path) ? (
                        <p className="mt-1 break-all font-mono text-[10px] text-violet-300/80">
                          {pack.display_path ||
                            displayMediaPath(pack.preview_clip_path || pack.clips_root_path)}
                        </p>
                      ) : null}
                      <p className="text-xs opacity-80">
                        {pack.category} · {pack.clip_count ?? 0} clips
                        {(visual?.duration_sec ?? pack.duration_sec)
                          ? ` · ${formatDuration(visual?.duration_sec ?? pack.duration_sec)}`
                          : ""}
                      </p>
                      {pack.preview_clip_path ? (
                        <div className="relative mt-2 w-24">
                          <video
                            muted
                            playsInline
                            preload="metadata"
                            className="aspect-[9/16] w-full rounded-lg bg-black object-cover"
                            src={productionMediaUrl(pack.preview_clip_path) ?? undefined}
                            onMouseEnter={(e) => e.currentTarget.play().catch(() => undefined)}
                            onMouseLeave={(e) => {
                              e.currentTarget.pause();
                              e.currentTarget.currentTime = 0;
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                          {(visual?.duration_sec ?? pack.duration_sec) ? (
                            <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] text-zinc-200">
                              {formatTimecode(visual?.duration_sec ?? pack.duration_sec)}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      {selectedAudio && selectedPack ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6">
          <h2 className="text-lg font-semibold text-zinc-100">Render combination</h2>
          <div className="mt-3 grid gap-4 text-sm text-zinc-300 md:grid-cols-2">
            <div>
              <p>
                <span className="text-zinc-500">Owner:</span> {owner}
              </p>
              <p>
                <span className="text-zinc-500">Audio:</span> {selectedAudio.display_id} — {selectedAudio.speaker}
              </p>
              <p>
                <span className="text-zinc-500">Visual:</span> {selectedPack.display_id} — {selectedPack.label}
                {visualDurationSec ? ` (${formatDuration(visualDurationSec)})` : ""}
              </p>
              {outputDurationSec ? (
                <p className="mt-2 font-medium text-violet-200">
                  Output length: {formatDuration(outputDurationSec)} — visual montage matched to audio
                </p>
              ) : null}
              {selectedPairing?.used_by_other_owner ? (
                <p className="mt-2 text-amber-300">Warning: used on {selectedPairing.other_owner}&apos;s channel.</p>
              ) : null}
              {selectedPairing?.used_by_selected_owner ? (
                <p className="mt-2 text-red-300">Already rendered for {owner}.</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <p className="text-xs text-zinc-500">
                Trim range (seconds). Default uses full audio — render cuts visuals to the same length.
              </p>
              <label className="block text-xs text-zinc-500">
                Start
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={trimStart}
                  onChange={(e) => setTrimStart(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1"
                />
              </label>
              <label className="block text-xs text-zinc-500">
                End{audioDurationSec ? ` (full clip: ${Math.round(audioDurationSec * 100) / 100})` : ""}
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={trimEnd}
                  onChange={(e) => setTrimEnd(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1"
                />
              </label>
              {outputDurationSec ? (
                <p className="text-xs text-zinc-400">
                  Selected span: {formatDuration(outputDurationSec)} ({formatTimecode(outputDurationSec)})
                </p>
              ) : null}
              <label className="flex items-center gap-2 text-xs text-zinc-400">
                <input type="checkbox" checked={forceRender} onChange={(e) => setForceRender(e.target.checked)} />
                Use anyway (same owner duplicate pairing)
              </label>
            </div>
          </div>
          {pairing?.advisory_reuse?.prior_usage_detected ? (
            <p className="mt-3 text-xs text-zinc-500">
              Advisory: prior library usage detected — {pairing.advisory_reuse.summary}
            </p>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={handleRender}
            className="mt-4 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-40"
          >
            {busy ? "Rendering…" : "Render combination"}
          </button>
          {message ? <p className="mt-3 text-sm text-zinc-300">{message}</p> : null}
          {message?.startsWith("Rendered Video") ? (
            <Link href="/library" className="mt-2 inline-block text-sm text-violet-300 hover:underline">
              Open library →
            </Link>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
