"use client";

import Link from "next/link";
import { useState } from "react";
import { RiskBadge, riskLevel } from "@/components/shared/risk-badge";
import {
  postCreateSourceMedia,
  postCreateGenerationJob,
  postWorkbenchCreateOriginal,
  postWorkbenchFindSource,
} from "@/lib/api";
import type { GenerationJobItem, WorkbenchCandidateItem } from "@/lib/types";

export function Workbench() {
  const [mode, setMode] = useState<"find" | "create">("find");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<WorkbenchCandidateItem[]>([]);
  const [lastJob, setLastJob] = useState<GenerationJobItem | null>(null);
  const [imageCount, setImageCount] = useState("6");
  const [videoCount, setVideoCount] = useState("2");

  async function handleFind() {
    if (!query.trim() || busy) return;
    setBusy(true);
    setMessage(null);
    const result = await postWorkbenchFindSource({ query, limit: 10 });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setCandidates(result.data.items);
    setMessage(`Found ${result.data.count} candidate(s)`);
  }

  async function handleCreateOriginal() {
    if (!query.trim() || busy) return;
    setBusy(true);
    setMessage(null);
    const result = await postWorkbenchCreateOriginal({
      query,
      image_count: Number(imageCount) || undefined,
      video_count: Number(videoCount) || undefined,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setLastJob(result.data);
    setMessage(`Created job ${result.data.job_key} — open Create to track or tell Cursor: "Generate all pending visual jobs."`);
  }

  async function useCandidate(
    candidate: WorkbenchCandidateItem,
    sourceMode: string,
  ) {
    if (!candidate.reference_id || busy) return;
    setBusy(true);
    setMessage(null);
    const source = await postCreateSourceMedia({
      source_mode: sourceMode,
      reference_id: candidate.reference_id,
    });
    if (!source.ok) {
      setBusy(false);
      setMessage(source.message);
      return;
    }
    const job = await postCreateGenerationJob({
      origin_type: "source_media",
      prompt_summary: candidate.title,
      image_count: Number(imageCount) || 6,
      video_count: Number(videoCount) || 0,
      reference_id: candidate.reference_id,
      source_media_id: source.data.item.id,
    });
    setBusy(false);
    if (!job.ok) {
      setMessage(job.message);
      return;
    }
    setLastJob(job.data);
    setMessage(`Source #${source.data.item.id} saved + job ${job.data.job_key} created. Continue in Create.`);
    window.location.href = `/create?source_media_id=${source.data.item.id}`;
  }

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode("find")}
          className={`rounded-lg px-4 py-2 text-sm ${mode === "find" ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
        >
          Find Source
        </button>
        <button
          type="button"
          onClick={() => setMode("create")}
          className={`rounded-lg px-4 py-2 text-sm ${mode === "create" ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
        >
          Create Original
        </button>
      </div>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={3}
          placeholder={
            mode === "find"
              ? 'Find unused Andrew Tate motivational audio about discipline…'
              : "Create 8 beautiful realistic luxury images and 2 moving AI clips…"
          }
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="text-xs text-zinc-400">
            Images
            <input
              type="number"
              value={imageCount}
              onChange={(e) => setImageCount(e.target.value)}
              className="ml-2 w-16 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm"
            />
          </label>
          <label className="text-xs text-zinc-400">
            Videos
            <input
              type="number"
              value={videoCount}
              onChange={(e) => setVideoCount(e.target.value)}
              className="ml-2 w-16 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={mode === "find" ? handleFind : handleCreateOriginal}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
          >
            {busy ? "Working…" : mode === "find" ? "Search" : "Create Generation Job"}
          </button>
        </div>
      </section>

      {message ? <p className="text-sm text-amber-300">{message}</p> : null}

      {lastJob ? (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm text-zinc-300">
          <p className="font-medium text-emerald-300">Job {lastJob.job_key}</p>
          <p className="mt-1">{lastJob.prompt_summary}</p>
          <p className="mt-1 text-xs text-zinc-500">
            {lastJob.image_count} images · {lastJob.video_count} videos · {lastJob.status}
          </p>
          <Link href="/create" className="mt-2 inline-block text-violet-300 hover:underline">
            Open production workspace →
          </Link>
        </div>
      ) : null}

      {mode === "find" && candidates.length > 0 ? (
        <div className="space-y-4">
          {candidates.map((c) => (
            <article key={c.reference_id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
              <h3 className="font-semibold text-zinc-100">{c.title}</h3>
              <p className="mt-1 line-clamp-2 text-xs text-zinc-500">{c.transcript_snippet}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <RiskBadge label="Reuse" score={c.reuse_confidence} level={riskLevel(c.reuse_confidence, true)} />
                <RiskBadge label="Rights" score={c.rights_confidence} level={riskLevel(c.rights_confidence)} />
                <RiskBadge label="Monetization" score={c.monetization_confidence} level={riskLevel(c.monetization_confidence)} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" disabled={busy} onClick={() => useCandidate(c, "audio")} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-200 disabled:opacity-50">Use Audio</button>
                <button type="button" disabled={busy} onClick={() => useCandidate(c, "video")} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-200 disabled:opacity-50">Use Video</button>
                <button type="button" disabled={busy} onClick={() => useCandidate(c, "topic")} className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-200 disabled:opacity-50">Use Topic</button>
                <Link href={`/create?reference_id=${c.reference_id}`} className="rounded border border-violet-500/40 px-3 py-1 text-xs text-violet-300">Create From This</Link>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
