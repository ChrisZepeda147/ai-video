"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchPublishingJobs,
  postCancelPublishingJob,
  postRetryPublishingJob,
} from "@/lib/api";
import type { PublishingJobItem } from "@/lib/types";

const QUEUE_STATUSES = ["scheduled", "queued", "publishing", "processing", "published", "failed"];

export function PublishingQueue() {
  const [jobs, setJobs] = useState<PublishingJobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const results = await Promise.all(QUEUE_STATUSES.map((s) => fetchPublishingJobs({ status: s, limit: 30 })));
    setLoading(false);
    const merged: PublishingJobItem[] = [];
    for (const r of results) {
      if (r.ok) merged.push(...r.data.items);
    }
    merged.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    setJobs(merged);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <p className="text-sm text-zinc-500">Loading publishing queue…</p>;
  if (jobs.length === 0) return null;

  return (
    <section className="mb-6 rounded-xl border border-sky-500/20 bg-sky-500/5 p-4">
      <h2 className="text-sm font-semibold text-sky-200">Publishing queue</h2>
      <ul className="mt-3 space-y-2">
        {jobs.map((j) => (
          <li key={j.id} className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-medium text-zinc-100">{j.account_display_name || `Account #${j.account_id}`}</span>
                <span className="text-zinc-500"> — {j.platform}</span>
                <span className="ml-2 rounded bg-zinc-800 px-1.5 py-0.5 text-xs capitalize text-zinc-300">{j.status}</span>
                {j.scheduled_at ? (
                  <span className="ml-2 text-xs text-zinc-500">{new Date(j.scheduled_at).toLocaleString()}</span>
                ) : null}
              </div>
              <div className="flex gap-2">
                {j.platform_url ? (
                  <a href={j.platform_url} target="_blank" rel="noreferrer" className="text-xs text-sky-300 hover:underline">Open Post</a>
                ) : null}
                {j.status === "scheduled" ? (
                  <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postCancelPublishingJob(j.id); setBusy(false); load(); }} className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-50">Cancel</button>
                ) : null}
                {j.status === "failed" ? (
                  <button type="button" disabled={busy} onClick={async () => { setBusy(true); await postRetryPublishingJob(j.id); setBusy(false); load(); }} className="text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-50">Retry</button>
                ) : null}
              </div>
            </div>
            {j.error_message ? <p className="mt-1 text-xs text-red-400">{j.error_message}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
