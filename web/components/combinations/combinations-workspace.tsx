"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  fetchCombinationCatalog,
  fetchCombinationStatus,
  postCombinationRender,
  productionMediaUrl,
} from "@/lib/api";
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
  const [audioStart, setAudioStart] = useState("");
  const [audioEnd, setAudioEnd] = useState("");

  const loadCatalog = useCallback(async () => {
    const result = await fetchCombinationCatalog(owner);
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

  const audioItems = useMemo(() => {
    if (!catalog) return [];
    if (selectedSpeaker) return catalog.audio_by_speaker[selectedSpeaker] ?? [];
    return Object.values(catalog.audio_by_speaker).flat();
  }, [catalog, selectedSpeaker]);

  const selectedAudio = audioItems.find((a) => a.component_id === selectedAudioId) ?? null;
  const selectedPack = catalog?.visual_packs.find((p) => p.id === selectedPackId) ?? null;
  const selectedPairing = pairing?.visuals.find((v) => v.visual_pack_id === selectedPackId);

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
    const result = await postCombinationRender({
      owner,
      audio_component_id: selectedAudioId,
      visual_pack_id: selectedPackId,
      force: forceRender,
      audio_start_sec: audioStart ? parseFloat(audioStart) : undefined,
      audio_end_sec: audioEnd ? parseFloat(audioEnd) : undefined,
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
    return <BackendOfflineBanner message="Start the API, then refresh." />;
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
                    <span className="text-xs text-zinc-500">{item.duration_sec ? `${item.duration_sec.toFixed(0)}s` : ""}</span>
                  </div>
                  <p className="mt-1 font-medium text-zinc-100">{item.speaker}</p>
                  <p className="line-clamp-2 text-xs text-zinc-500">{item.transcript_excerpt || item.video_title}</p>
                  {item.local_path ? (
                    <audio
                      controls
                      preload="none"
                      className="mt-2 h-8 w-full"
                      src={productionMediaUrl(item.local_path) ?? undefined}
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="text-lg font-semibold text-zinc-100">Visual packs</h2>
          {!selectedAudioId ? (
            <p className="mt-3 text-sm text-zinc-500">Select an audio clip to see pairing status.</p>
          ) : (
            <ul className="mt-4 max-h-[420px] space-y-2 overflow-y-auto">
              {(pairing?.visuals ?? catalog?.visual_packs ?? []).map((item) => {
                const visual = "status" in item ? item : null;
                const pack = visual
                  ? catalog?.visual_packs.find((p) => p.id === visual.visual_pack_id)
                  : (item as CombinationCatalog["visual_packs"][number]);
                if (!pack) return null;
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
                      <div className="flex items-center justify-between">
                        <span className="font-mono">{pack.display_id || pack.id}</span>
                        <span className="text-xs">{visual ? statusLabel(visual, owner) : pack.category}</span>
                      </div>
                      <p className="mt-1 font-medium">{pack.label}</p>
                      <p className="text-xs opacity-80">
                        {pack.category} · {pack.clip_count ?? 0} clips
                      </p>
                      {pack.preview_clip_path ? (
                        <video
                          muted
                          playsInline
                          preload="metadata"
                          className="mt-2 aspect-[9/16] w-24 rounded-lg bg-black object-cover"
                          src={productionMediaUrl(pack.preview_clip_path) ?? undefined}
                          onMouseEnter={(e) => e.currentTarget.play().catch(() => undefined)}
                          onMouseLeave={(e) => {
                            e.currentTarget.pause();
                            e.currentTarget.currentTime = 0;
                          }}
                          onClick={(e) => e.stopPropagation()}
                        />
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
              </p>
              {selectedPairing?.used_by_other_owner ? (
                <p className="mt-2 text-amber-300">Warning: used on {selectedPairing.other_owner}&apos;s channel.</p>
              ) : null}
              {selectedPairing?.used_by_selected_owner ? (
                <p className="mt-2 text-red-300">Already rendered for {owner}.</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <label className="block text-xs text-zinc-500">
                Audio start (sec)
                <input
                  value={audioStart}
                  onChange={(e) => setAudioStart(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1"
                />
              </label>
              <label className="block text-xs text-zinc-500">
                Audio end (sec)
                <input
                  value={audioEnd}
                  onChange={(e) => setAudioEnd(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1"
                />
              </label>
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
