"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  fetchConcepts,
  fetchDiscoveryNiches,
  fetchGenerationJobs,
  postApproveConcepts,
  postCreateGenerationJob,
  postGenerateConcepts,
  postImportGenerationJob,
  postRejectConcepts,
  postShortlistConcepts,
} from "@/lib/api";
import type { ConceptItem, GenerationJobItem, NicheCoverageItem } from "@/lib/types";
import { ShortAssemblyPanel } from "@/components/create/short-assembly-panel";

const STATUSES = ["", "generated", "shortlisted", "approved", "rejected"];

function StatusBadge({ status }: { status: string }) {
  const tones: Record<string, string> = {
    generated: "bg-zinc-600/30 text-zinc-300",
    shortlisted: "bg-sky-500/15 text-sky-300",
    approved: "bg-emerald-500/15 text-emerald-300",
    rejected: "bg-red-500/15 text-red-300",
  };
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-medium capitalize ${tones[status] || "bg-zinc-700 text-zinc-400"}`}
    >
      {status}
    </span>
  );
}

export function CreateWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [niches, setNiches] = useState<NicheCoverageItem[]>([]);
  const [concepts, setConcepts] = useState<ConceptItem[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [jobs, setJobs] = useState<GenerationJobItem[]>([]);
  const [imageCount, setImageCount] = useState("5");
  const [videoCount, setVideoCount] = useState("0");
  const [selectedConcept, setSelectedConcept] = useState<ConceptItem | null>(null);

  const [niche, setNiche] = useState(searchParams.get("niche") || "");
  const [status, setStatus] = useState(searchParams.get("status") || "");
  const [referenceId, setReferenceId] = useState(searchParams.get("reference_id") || "");
  const sourceMediaIdParam = searchParams.get("source_media_id") || "";
  const projectIdParam = searchParams.get("project_id") || "";

  const loadConcepts = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    const result = await fetchConcepts({
      niche: niche || undefined,
      status: status || undefined,
      reference_id: referenceId ? Number(referenceId) : undefined,
      limit: 200,
    });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      setConcepts([]);
      return;
    }
    setConcepts(result.data.items);
    setSelected(new Set());
  }, [niche, status, referenceId]);

  const loadJobs = useCallback(async () => {
    const result = await fetchGenerationJobs({ limit: 20 });
    if (result.ok) setJobs(result.data.items);
  }, []);

  useEffect(() => {
    fetchDiscoveryNiches().then((r) => {
      if (r.ok) setNiches(r.data.items);
    });
    loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    loadConcepts();
  }, [loadConcepts]);

  function applyFilters() {
    const params = new URLSearchParams();
    if (niche) params.set("niche", niche);
    if (status) params.set("status", status);
    if (referenceId) params.set("reference_id", referenceId);
    router.push(`/create?${params.toString()}`);
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runBatch(
    action: "shortlist" | "approve" | "reject",
  ) {
    if (selected.size === 0 || busy) return;
    setBusy(true);
    const ids = Array.from(selected);
    const fn =
      action === "shortlist"
        ? postShortlistConcepts
        : action === "approve"
          ? postApproveConcepts
          : postRejectConcepts;
    const result = await fn(ids);
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`${action}: updated ${result.data.count} concept(s)`);
    await loadConcepts();
  }

  async function handleCreateGenerationJob() {
    if (busy) return;
    const concept = selectedConcept ?? concepts.find((c) => c.status === "approved") ?? concepts[0];
    if (!concept) {
      setMessage("Select or approve a concept first, or use Workbench for freeform jobs.");
      return;
    }
    setBusy(true);
    const result = await postCreateGenerationJob({
      origin_type: "concept",
      prompt_summary: concept.visual_premise || concept.title,
      image_count: Number(imageCount) || 5,
      video_count: Number(videoCount) || 0,
      reference_id: concept.reference_id,
      concept_id: concept.id,
      niche: concept.niche || undefined,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Generation job ${result.data.job_key} created. Generate in Cursor, then Import.`);
    await loadJobs();
  }

  async function handleImportJob(jobId: number) {
    if (busy) return;
    setBusy(true);
    const result = await postImportGenerationJob(jobId);
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Imported ${result.data.imported}, skipped ${result.data.skipped}`);
    await loadJobs();
  }

  async function handleGenerateForRef() {
    const ref = Number(referenceId);
    if (!ref || busy) return;
    setBusy(true);
    const result = await postGenerateConcepts(ref, { count: 5, niche: niche || undefined });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Generated ${result.data.stored} new concept(s)`);
    await loadConcepts();
  }

  return (
    <div>
      <ShortAssemblyPanel
        initialSourceMediaId={sourceMediaIdParam}
        initialProjectId={projectIdParam}
        selectedConcept={selectedConcept}
        busy={busy}
        setBusy={setBusy}
        onMessage={setMessage}
      />

      <section className="mb-6 rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
        <h2 className="text-sm font-semibold text-violet-200">Production — generation jobs</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Visuals match mood/topic/emotion — not every spoken line. Jobs export to{" "}
          <code className="text-zinc-400">data/generation_jobs/</code> for Cursor handoff.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {[3, 5, 8, 10].map((n) => (
            <button key={n} type="button" onClick={() => setImageCount(String(n))} className={`rounded px-2 py-1 text-xs ${imageCount === String(n) ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-400"}`}>
              {n} img
            </button>
          ))}
          {[0, 1, 2].map((n) => (
            <button key={n} type="button" onClick={() => setVideoCount(String(n))} className={`rounded px-2 py-1 text-xs ${videoCount === String(n) ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-400"}`}>
              {n} vid
            </button>
          ))}
          <button type="button" disabled={busy} onClick={handleCreateGenerationJob} className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white disabled:opacity-50">
            Create Generation Job
          </button>
          <Link href="/workbench" className="text-xs text-violet-300 hover:underline">Freeform in Workbench →</Link>
          <Link href="/review" className="text-xs text-zinc-400 hover:underline">Review queue →</Link>
        </div>
        {jobs.length > 0 ? (
          <ul className="mt-4 space-y-2 text-xs text-zinc-400">
            {jobs.slice(0, 5).map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-2 rounded border border-zinc-800 bg-zinc-950/50 px-3 py-2">
                <span className="font-medium text-zinc-200">{j.job_key}</span>
                <span>{j.status}</span>
                <span>{j.image_count}img / {j.video_count}vid</span>
                <button type="button" disabled={busy} onClick={() => handleImportJob(j.id)} className="rounded border border-zinc-700 px-2 py-0.5 text-zinc-300 disabled:opacity-50">Import</button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="mb-6 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="grid gap-3 md:grid-cols-4">
          <select
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          >
            <option value="">All niches</option>
            {niches.map((n) => (
              <option key={n.niche} value={n.niche}>
                {n.niche}
              </option>
            ))}
          </select>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          >
            {STATUSES.map((s) => (
              <option key={s || "all"} value={s}>
                {s ? s : "All statuses"}
              </option>
            ))}
          </select>
          <input
            type="number"
            placeholder="Reference ID"
            value={referenceId}
            onChange={(e) => setReferenceId(e.target.value)}
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
          <button
            type="button"
            onClick={applyFilters}
            className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-100 hover:bg-zinc-700"
          >
            Apply filters
          </button>
        </div>
        {referenceId ? (
          <button
            type="button"
            disabled={busy}
            onClick={handleGenerateForRef}
            className="mt-3 rounded-lg border border-violet-500/40 bg-violet-600/20 px-4 py-2 text-sm text-violet-200 hover:bg-violet-600/30 disabled:opacity-50"
          >
            Generate 5 more concepts for reference {referenceId}
          </button>
        ) : null}
      </section>

      {selected.size > 0 ? (
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="text-sm text-zinc-400">{selected.size} selected</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => runBatch("shortlist")}
            className="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
          >
            Shortlist
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => runBatch("approve")}
            className="rounded-lg bg-emerald-600/80 px-3 py-1.5 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => runBatch("reject")}
            className="rounded-lg border border-red-500/40 px-3 py-1.5 text-sm text-red-300 hover:bg-red-500/10 disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      ) : null}

      {message ? <p className="mb-4 text-sm text-amber-300">{message}</p> : null}

      {loading ? (
        <p className="text-sm text-zinc-500">Loading concepts…</p>
      ) : concepts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No concepts yet. Analyze a reference on Discover, then generate ideas.
        </div>
      ) : (
        <div className="space-y-4">
          {concepts.map((c) => (
            <article
              key={c.id}
              onClick={() => setSelectedConcept(c)}
              className={`rounded-xl border p-4 cursor-pointer ${
                selectedConcept?.id === c.id
                  ? "border-violet-400/60 bg-violet-500/10"
                  : selected.has(c.id)
                  ? "border-violet-500/50 bg-violet-500/5"
                  : "border-zinc-800 bg-zinc-900/40"
              }`}
            >
              <div className="flex flex-wrap items-start gap-3">
                <input
                  type="checkbox"
                  checked={selected.has(c.id)}
                  onChange={() => toggleSelect(c.id)}
                  className="mt-1"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold text-zinc-100">{c.title}</h3>
                    <StatusBadge status={c.status} />
                  </div>
                  <p className="mt-1 text-xs text-zinc-500">
                    Ref: {c.reference_title ?? c.reference_id}
                    {c.reference_virality_score != null
                      ? ` · Score ${Math.round(c.reference_virality_score)}`
                      : ""}
                    {c.niche ? ` · ${c.niche}` : ""}
                    {c.variation_family ? ` · ${c.variation_family}` : ""}
                  </p>
                  {c.hook_idea ? (
                    <p className="mt-2 text-sm text-zinc-300">
                      <span className="text-zinc-500">Hook:</span> {c.hook_idea}
                    </p>
                  ) : null}
                  {c.visual_premise ? (
                    <p className="mt-1 text-sm text-zinc-400">{c.visual_premise}</p>
                  ) : null}
                  {c.setting ? (
                    <p className="mt-1 text-xs text-zinc-500">Setting: {c.setting}</p>
                  ) : null}
                  {c.story_premise ? (
                    <p className="mt-1 text-xs text-zinc-500">Story: {c.story_premise}</p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1">
                  <button
                    type="button"
                    disabled={busy || c.status !== "generated"}
                    onClick={async () => {
                      setBusy(true);
                      await postShortlistConcepts([c.id]);
                      setBusy(false);
                      await loadConcepts();
                    }}
                    className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 disabled:opacity-40"
                  >
                    Shortlist
                  </button>
                  <button
                    type="button"
                    disabled={busy || !["generated", "shortlisted"].includes(c.status)}
                    onClick={async () => {
                      setBusy(true);
                      await postApproveConcepts([c.id]);
                      setBusy(false);
                      await loadConcepts();
                    }}
                    className="rounded bg-emerald-600/60 px-2 py-1 text-xs text-white disabled:opacity-40"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={busy || c.status === "rejected"}
                    onClick={async () => {
                      setBusy(true);
                      await postRejectConcepts([c.id]);
                      setBusy(false);
                      await loadConcepts();
                    }}
                    className="rounded border border-red-500/30 px-2 py-1 text-xs text-red-300 disabled:opacity-40"
                  >
                    Reject
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
