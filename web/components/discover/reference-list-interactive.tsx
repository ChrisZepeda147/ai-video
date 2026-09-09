"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { AnalysisModal } from "@/components/discover/analysis-modal";
import {
  fetchReferenceAnalysis,
  postAnalyzeReference,
  postCreateSourceMedia,
  postGenerateConcepts,
} from "@/lib/api";
import { formatReferenceViews } from "@/lib/dashboard-stats";
import type { AnalysisItem, ReferenceItem } from "@/lib/types";

function ViralityBadge({ score }: { score: number | null | undefined }) {
  if (score == null) {
    return <span className="text-xs text-zinc-500">—</span>;
  }
  return (
    <span className="inline-flex rounded-md bg-violet-500/15 px-2 py-0.5 text-xs font-semibold text-violet-300 ring-1 ring-violet-500/30">
      {Math.round(score)}
    </span>
  );
}

export function ReferenceListInteractive({ items }: { items: ReferenceItem[] }) {
  const router = useRouter();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisItem | null>(null);
  const [analysisTitle, setAnalysisTitle] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [generateFor, setGenerateFor] = useState<ReferenceItem | null>(null);
  const [conceptCount, setConceptCount] = useState("5");

  async function handleAnalyze(ref: ReferenceItem, reanalyze = false) {
    if (busyId !== null) return;
    setBusyId(ref.id);
    setMessage(null);
    const result = await postAnalyzeReference(ref.id, reanalyze);
    setBusyId(null);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    const item = result.data.item;
    if (item) {
      setAnalysis(item);
      setAnalysisTitle(ref.title);
      router.refresh();
    }
  }

  async function handleViewAnalysis(ref: ReferenceItem) {
    if (busyId !== null) return;
    setBusyId(ref.id);
    const result = await fetchReferenceAnalysis(ref.id);
    setBusyId(null);
    if (!result.ok || !result.data.item) {
      setMessage(result.ok ? "No analysis yet. Click Analyze first." : result.message);
      return;
    }
    setAnalysis(result.data.item);
    setAnalysisTitle(ref.title);
  }

  async function handleGenerate(ref: ReferenceItem) {
    if (busyId !== null) return;
    setBusyId(ref.id);
    setMessage(null);
    const count = Number(conceptCount) || 5;
    const result = await postGenerateConcepts(ref.id, { count });
    setBusyId(null);
    setGenerateFor(null);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(
      `Generated ${result.data.stored} concept(s) for reference ${ref.id}. Rejected similar: ${result.data.rejected_similar}`,
    );
    router.push(`/create?reference_id=${ref.id}`);
  }

  async function handleUseSource(ref: ReferenceItem, sourceMode: string) {
    if (busyId !== null) return;
    setBusyId(ref.id);
    setMessage(null);
    const result = await postCreateSourceMedia({
      source_mode: sourceMode,
      reference_id: ref.id,
    });
    setBusyId(null);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    const reuse = result.data.risk_scores.reuse_confidence;
    setMessage(
      `Source saved (${sourceMode}). Reuse: ${reuse ?? 0}% — advisory only. Opening Create…`,
    );
    router.push(`/create?reference_id=${ref.id}`);
  }

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 px-6 py-12 text-center">
        <p className="text-sm font-medium text-zinc-300">No references found</p>
        <p className="mt-2 text-sm text-zinc-500">Run Scan YouTube above to populate the catalog.</p>
      </div>
    );
  }

  return (
    <>
      {message ? <p className="mb-4 text-sm text-amber-300">{message}</p> : null}

      <div className="space-y-4">
        {items.map((item) => (
          <article
            key={item.id}
            className="flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 lg:flex-row"
          >
            <div className="relative h-36 w-full shrink-0 overflow-hidden rounded-lg bg-zinc-800 lg:h-28 lg:w-48">
              {item.thumbnail_url ? (
                <Image
                  src={item.thumbnail_url}
                  alt=""
                  fill
                  className="object-cover"
                  sizes="192px"
                  unoptimized
                />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-zinc-500">
                  No thumbnail
                </div>
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-orange-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-orange-300 ring-1 ring-orange-500/30">
                  Reference only
                </span>
                {item.has_analysis ? (
                  <span className="rounded-md bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium text-violet-300">
                    Creative DNA
                  </span>
                ) : null}
              </div>
              <h3 className="mt-2 text-base font-semibold text-zinc-100">{item.title}</h3>
              <p className="mt-1 text-sm text-zinc-400">{item.channel ?? "Unknown channel"}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {item.niches.map((tag) => (
                  <span
                    key={`${item.id}-${tag.niche}`}
                    className="rounded-md bg-zinc-800 px-2 py-0.5 text-xs capitalize text-zinc-300"
                  >
                    {tag.niche}
                  </span>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-zinc-400">
                <span>{formatReferenceViews(item.view_count)} views</span>
                <span>{item.age_label ?? "—"} old</span>
                <ViralityBadge score={item.virality_score} />
                <span>{item.concepts_generated} concepts</span>
              </div>
            </div>

            <div className="flex shrink-0 flex-col gap-2 lg:items-stretch">
              <button
                type="button"
                disabled={busyId !== null}
                onClick={() => handleAnalyze(item)}
                className="rounded-lg bg-violet-600/80 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                {busyId === item.id ? "Working…" : "Analyze"}
              </button>
              {item.has_analysis ? (
                <button
                  type="button"
                  disabled={busyId !== null}
                  onClick={() => handleViewAnalysis(item)}
                  className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
                >
                  View DNA
                </button>
              ) : null}
              <button
                type="button"
                disabled={busyId !== null}
                onClick={() => setGenerateFor(item)}
                className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
              >
                Create Ideas
              </button>
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
              >
                Open YouTube
                <ExternalLink className="h-4 w-4" />
              </a>
              <div className="mt-1 grid grid-cols-2 gap-1">
                <button type="button" disabled={busyId !== null} onClick={() => handleUseSource(item, "topic")} className="rounded border border-sky-500/30 px-2 py-1 text-[11px] text-sky-300 disabled:opacity-50">Use Topic</button>
                <button type="button" disabled={busyId !== null} onClick={() => handleUseSource(item, "audio")} className="rounded border border-sky-500/30 px-2 py-1 text-[11px] text-sky-300 disabled:opacity-50">Use Audio</button>
                <button type="button" disabled={busyId !== null} onClick={() => handleUseSource(item, "video")} className="rounded border border-sky-500/30 px-2 py-1 text-[11px] text-sky-300 disabled:opacity-50">Use Video</button>
                <button type="button" disabled={busyId !== null} onClick={() => handleUseSource(item, "original")} className="rounded border border-sky-500/30 px-2 py-1 text-[11px] text-sky-300 disabled:opacity-50">Original Version</button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {analysis ? (
        <AnalysisModal
          analysis={analysis}
          referenceTitle={analysisTitle}
          onClose={() => setAnalysis(null)}
        />
      ) : null}

      {generateFor ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-950 p-6">
            <h3 className="font-semibold text-zinc-100">Generate concepts</h3>
            <p className="mt-1 text-sm text-zinc-400">{generateFor.title}</p>
            <label className="mt-4 block text-sm text-zinc-400">
              Count
              <select
                value={conceptCount}
                onChange={(e) => setConceptCount(e.target.value)}
                className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100"
              >
                <option value="3">3</option>
                <option value="5">5</option>
                <option value="10">10</option>
              </select>
            </label>
            <div className="mt-6 flex gap-2">
              <button
                type="button"
                disabled={busyId !== null}
                onClick={() => handleGenerate(generateFor)}
                className="flex-1 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                Generate
              </button>
              <button
                type="button"
                onClick={() => setGenerateFor(null)}
                className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300"
              >
                Cancel
              </button>
            </div>
            <Link
              href={`/create?reference_id=${generateFor.id}`}
              className="mt-3 block text-center text-xs text-zinc-500 hover:text-zinc-300"
            >
              Open Create workspace →
            </Link>
          </div>
        </div>
      ) : null}
    </>
  );
}
