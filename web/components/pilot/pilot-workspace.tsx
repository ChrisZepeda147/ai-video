"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  fetchPilotBatch,
  fetchPilotBatches,
  fetchPilotResults,
  postCreatePilotBatch,
  postRunPilotPending,
} from "@/lib/api";
import { fetchPublishingAccounts } from "@/lib/api";
import type { PilotBatchResponse, PilotBatchItemResponse, PublishingAccountItem } from "@/lib/types";

const STAGE_LABELS: Record<string, string> = {
  reference: "Reference",
  source_acquired: "Source acquired",
  transcript: "Transcript",
  visual_generation: "Visual generation",
  visual_approval: "Visual approval",
  timeline: "Timeline",
  render: "Render",
  final_approval: "Final approval",
  publishing: "Publishing",
  analytics: "Analytics",
};

function StageIcon({ status }: { status: string }) {
  if (status === "complete" || status === "skipped") return <span className="text-emerald-400">✓</span>;
  if (status === "failed") return <span className="text-red-400">✗</span>;
  if (status === "waiting_cursor") return <span className="text-violet-400">Cursor</span>;
  if (status === "waiting_human") return <span className="text-amber-400">You</span>;
  if (status === "in_progress") return <span className="text-sky-400">…</span>;
  return <span className="text-zinc-600">—</span>;
}

function ItemProgress({ item }: { item: PilotBatchItemResponse }) {
  return (
    <div className="mt-3 space-y-1 text-xs">
      {Object.entries(STAGE_LABELS).map(([key, label]) => {
        const stage = item.stages[key];
        if (!stage) return null;
        return (
          <div key={key} className="flex items-center gap-2 text-zinc-400">
            <StageIcon status={stage.status} />
            <span className="w-36 shrink-0 text-zinc-500">{label}</span>
            <span className="min-w-0 truncate text-zinc-400">{stage.message}</span>
            {stage.entity_id ? (
              <span className="shrink-0 text-zinc-600">#{stage.entity_id}</span>
            ) : null}
          </div>
        );
      })}
      {item.error_message ? (
        <div className="mt-2 rounded border border-red-900/50 bg-red-950/30 p-2 text-red-300">
          <p className="font-medium">Failed: {item.error_stage}</p>
          <p>{item.error_message}</p>
          <div className="mt-2 flex gap-2">
            {item.source_media_id ? (
              <Link href={`/create?source_id=${item.source_media_id}`} className="underline">Open source</Link>
            ) : null}
            {item.production_project_id ? (
              <Link href={`/create?project_id=${item.production_project_id}`} className="underline">Open project</Link>
            ) : null}
            {item.generation_job_id ? (
              <span className="text-zinc-500">Job #{item.generation_job_id}</span>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function PilotWorkspace() {
  const [batches, setBatches] = useState<PilotBatchResponse[]>([]);
  const [active, setActive] = useState<PilotBatchResponse | null>(null);
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [accounts, setAccounts] = useState<PublishingAccountItem[]>([]);
  const [niche, setNiche] = useState("luxury");
  const [accountId, setAccountId] = useState<number | "">("");
  const [batchSize, setBatchSize] = useState(3);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [batchRes, acctRes] = await Promise.all([fetchPilotBatches(), fetchPublishingAccounts()]);
    setLoading(false);
    if (batchRes.ok) {
      setBatches(batchRes.data.items);
      if (batchRes.data.items[0]) {
        const detail = await fetchPilotBatch(batchRes.data.items[0].id);
        if (detail.ok) setActive(detail.data);
      }
    }
    if (acctRes.ok) setAccounts(acctRes.data.items.filter((a) => a.platform === "youtube"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createBatch() {
    setBusy(true);
    setMessage(null);
    const result = await postCreatePilotBatch({
      name: `${niche} Pilot`,
      niche,
      account_id: accountId === "" ? undefined : Number(accountId),
      batch_size: batchSize,
      use_first_batch_mix: true,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setActive(result.data);
    setMessage(`Created pilot batch #${result.data.id} with ${result.data.items.length} Shorts`);
    load();
  }

  async function runPending() {
    if (!active) return;
    setBusy(true);
    const result = await postRunPilotPending({ batch_id: active.id });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    const parts = [`Ran ${result.data.tasks.length} automated task(s)`];
    if (result.data.human_required.length) {
      parts.push(`${result.data.human_required.length} need human action`);
    }
    if (result.data.errors.length) {
      parts.push(`${result.data.errors.length} error(s)`);
    }
    setMessage(parts.join(" · "));
    const detail = await fetchPilotBatch(active.id);
    if (detail.ok) setActive(detail.data);
    const res = await fetchPilotResults(active.id);
    if (res.ok) setResults(res.data.items);
  }

  async function selectBatch(id: number) {
    const detail = await fetchPilotBatch(id);
    if (detail.ok) {
      setActive(detail.data);
      const res = await fetchPilotResults(id);
      if (res.ok) setResults(res.data.items);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h2 className="text-sm font-semibold text-zinc-200">Start pilot batch</h2>
        <p className="mt-1 text-xs text-zinc-500">
          First batch mix: podcast audio + source video + original freeform — uses existing Workbench, generation, and production systems.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
            placeholder="Niche"
            className="rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          />
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}
            className="rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          >
            <option value="">Destination account (optional)</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name} ({a.auth_status})
              </option>
            ))}
          </select>
          <input
            type="number"
            min={1}
            max={10}
            value={batchSize}
            onChange={(e) => setBatchSize(Number(e.target.value))}
            className="w-20 rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={busy || !niche.trim()}
            onClick={createBatch}
            className="rounded bg-violet-600 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            Create batch
          </button>
          <button
            type="button"
            disabled={busy || !active}
            onClick={runPending}
            className="rounded border border-zinc-700 px-4 py-2 text-sm text-zinc-200 disabled:opacity-50"
          >
            Run pending tasks
          </button>
        </div>
        {message ? <p className="mt-3 text-sm text-amber-300">{message}</p> : null}
      </section>

      {loading ? <p className="text-sm text-zinc-500">Loading pilot batches…</p> : null}

      {batches.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {batches.map((b) => (
            <button
              key={b.id}
              type="button"
              onClick={() => selectBatch(b.id)}
              className={`rounded border px-3 py-1 text-xs ${
                active?.id === b.id ? "border-violet-500 text-violet-300" : "border-zinc-700 text-zinc-400"
              }`}
            >
              #{b.id} {b.name}
            </button>
          ))}
        </div>
      ) : null}

      {active ? (
        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-zinc-200">
            {active.name} · {active.niche} · {active.status}
          </h2>
          {active.items.map((item) => (
            <article key={item.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold text-zinc-100">{item.slot_label ?? `Item ${item.id}`}</h3>
                <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">{item.strategy}</span>
                <span className="text-xs text-zinc-500">{item.format_profile}</span>
                <span className="text-xs capitalize text-zinc-500">{item.status}</span>
              </div>
              {item.notes ? <p className="mt-1 text-xs text-zinc-500">{item.notes}</p> : null}
              <ItemProgress item={item} />
            </article>
          ))}
        </section>
      ) : null}

      {results.length > 0 ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="text-sm font-semibold text-zinc-200">Pilot comparison</h2>
          <p className="mt-1 text-xs text-zinc-500">Advisory only — 3 videos is not enough to prove causation.</p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-zinc-500">
                <tr>
                  <th className="py-2 pr-4">Short</th>
                  <th className="py-2 pr-4">Format</th>
                  <th className="py-2 pr-4">Views</th>
                  <th className="py-2 pr-4">Score</th>
                </tr>
              </thead>
              <tbody className="text-zinc-300">
                {results.map((row) => {
                  const metrics = (row.metrics as Record<string, unknown>) || {};
                  return (
                    <tr key={String(row.item_id)} className="border-t border-zinc-800">
                      <td className="py-2 pr-4">{String(row.slot_label)}</td>
                      <td className="py-2 pr-4">{String(row.strategy)}</td>
                      <td className="py-2 pr-4">{String(metrics.views ?? "—")}</td>
                      <td className="py-2 pr-4">{String(metrics.performance_score ?? "—")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
