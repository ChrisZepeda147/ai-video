"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  fetchCommandJob,
  fetchCommandStatus,
  fetchCommands,
  fetchHealth,
  postCommand,
  productionMediaUrl,
} from "@/lib/api";
import type { CommandJob } from "@/lib/types";

type CommandWorkspaceProps = {
  videoId?: number;
  initialSessionId?: string;
  placeholder?: string;
};

export function CommandWorkspace({
  videoId,
  initialSessionId,
  placeholder = "Make an Andrew Tate motivational video with new rooftop visuals.",
}: CommandWorkspaceProps) {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [cursorAvailable, setCursorAvailable] = useState<boolean | null>(null);
  const [command, setCommand] = useState("");
  const [sessionId, setSessionId] = useState(initialSessionId || "");
  const [busy, setBusy] = useState(false);
  const [activeJob, setActiveJob] = useState<CommandJob | null>(null);
  const [history, setHistory] = useState<CommandJob[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [batchJobs, setBatchJobs] = useState<CommandJob[]>([]);

  const load = useCallback(async () => {
    const health = await fetchHealth();
    setBackendOnline(health.ok);
    if (!health.ok) return;
    const status = await fetchCommandStatus();
    if (status.ok) setCursorAvailable(status.data.cursor_agent_available);
    const list = await fetchCommands(30);
    if (list.ok) setHistory(list.data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!activeJob || !["queued", "running"].includes(activeJob.status)) return;
    const timer = setInterval(async () => {
      const result = await fetchCommandJob(activeJob.job_key);
      if (result.ok) {
        setActiveJob(result.data);
        if (["completed", "failed", "needs_review"].includes(result.data.status)) {
          load();
        }
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [activeJob, load]);

  async function handleSubmit() {
    if (busy || !command.trim() || backendOnline === false) return;
    setBusy(true);
    setMessage(null);
    const result = await postCommand({
      command: command.trim(),
      video_id: videoId,
      parent_video_id: videoId,
      session_id: sessionId.trim() || undefined,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    const data = result.data as CommandJob & { batch?: boolean; jobs?: CommandJob[] };
    if (data.batch && data.jobs?.length) {
      setBatchJobs(data.jobs);
      setActiveJob(data.jobs[0]);
      setMessage(`Batch started — ${data.jobs.length} Cursor jobs queued.`);
    } else {
      setActiveJob(data);
      setMessage("Command sent to Cursor Agent…");
    }
    if (data.cursor_session_id) setSessionId(data.cursor_session_id);
    setCommand("");
  }

  const previewPath = activeJob?.final_output_path;
  const agentText =
    activeJob?.agent_result ||
    activeJob?.stdout_log ||
    activeJob?.stderr_log ||
    activeJob?.error_message ||
    "";

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {backendOnline === false ? (
        <BackendOfflineBanner message="From repo root run npm run dev, then refresh." />
      ) : null}

      {cursorAvailable === false ? (
        <p className="rounded-xl border border-amber-900/50 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          Cursor Agent CLI not detected. Install `agent` or set <code>CURSOR_BRIDGE_DRY_RUN=1</code> for testing.
        </p>
      ) : null}

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6">
        <h2 className="text-lg font-semibold text-zinc-100">Command Cursor</h2>
        <p className="mt-2 text-sm text-zinc-400">
          Plain English → Cursor Agent runs in this repo using existing Python tools and project rules.
          {videoId ? ` Context: Video ${videoId}.` : ""} Mention Video N to include that project as context.
          Say &quot;make 5 new videos&quot; for batch production.
        </p>
        <textarea
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          rows={4}
          placeholder={placeholder}
          className="mt-4 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-3 text-sm text-zinc-100"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={busy || !command.trim() || backendOnline === false}
            onClick={handleSubmit}
            className="rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-40"
          >
            {busy ? "Sending…" : "Run command"}
          </button>
          {sessionId ? (
            <span className="text-xs text-zinc-500">Session: {sessionId.slice(0, 12)}…</span>
          ) : null}
        </div>
      </section>

      {message ? <p className="text-sm text-zinc-300">{message}</p> : null}

      {batchJobs.length > 1 ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/30 p-4 text-sm">
          <h3 className="font-semibold text-zinc-200">Batch jobs ({batchJobs.length})</h3>
          <ul className="mt-2 space-y-1">
            {batchJobs.map((item) => (
              <li key={item.job_key} className="text-zinc-400">
                {item.job_key} — <span className="capitalize">{item.status}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {activeJob ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm">
          <p className="font-medium capitalize text-zinc-100">
            {activeJob.job_key} — {activeJob.status}
          </p>
          <p className="mt-2 text-zinc-400">{activeJob.user_command}</p>
          {agentText ? (
            <pre className="mt-4 max-h-80 overflow-auto rounded-lg bg-zinc-950 p-3 text-xs text-zinc-300 whitespace-pre-wrap">
              {agentText}
            </pre>
          ) : null}
          {activeJob.production_video_id ? (
            <Link
              href={`/library/${activeJob.production_video_id}`}
              className="mt-3 inline-block text-sm text-violet-300 hover:underline"
            >
              Open Video {activeJob.production_video_id} in library →
            </Link>
          ) : null}
          {previewPath ? (
            <video
              src={productionMediaUrl(previewPath) ?? undefined}
              controls
              className="mt-4 aspect-[9/16] w-[200px] rounded-lg bg-zinc-950"
            />
          ) : null}
        </section>
      ) : null}

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/30 p-4">
        <h3 className="text-sm font-semibold text-zinc-200">Recent commands</h3>
        <ul className="mt-3 space-y-2">
          {history.length === 0 ? (
            <li className="text-sm text-zinc-500">No commands yet.</li>
          ) : (
            history.map((job) => (
              <li key={job.job_key}>
                <button
                  type="button"
                  onClick={() => setActiveJob(job)}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-left text-sm hover:border-zinc-700"
                >
                  <span className="block truncate text-zinc-200">{job.user_command}</span>
                  <span className="text-xs capitalize text-zinc-500">
                    {job.job_key} · {job.status}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
        <Link href="/library" className="mt-4 inline-block text-sm text-violet-300 hover:underline">
          Open production library →
        </Link>
      </section>
    </div>
  );
}
