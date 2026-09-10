"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  fetchCommandJob,
  fetchCommandStatus,
  fetchHealth,
  fetchShortBuildDefaults,
  postCommand,
  productionMediaUrl,
} from "@/lib/api";
import { composeMakeShortCommand, type MakeShortOwner } from "@/lib/make-short-command";
import type { CommandJob, ShortBuildDefaults } from "@/lib/types";

export function MakeShortWorkspace() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [cursorAvailable, setCursorAvailable] = useState<boolean | null>(null);
  const [defaults, setDefaults] = useState<ShortBuildDefaults | null>(null);
  const [audioQuery, setAudioQuery] = useState("");
  const [brollQuery, setBrollQuery] = useState("");
  const [instructions, setInstructions] = useState("");
  const [owner, setOwner] = useState<MakeShortOwner>("chris");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<CommandJob | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadDefaults = useCallback(async () => {
    const health = await fetchHealth();
    setBackendOnline(health.ok);
    if (!health.ok) return;
    const [defaultsResult, statusResult] = await Promise.all([
      fetchShortBuildDefaults(),
      fetchCommandStatus(),
    ]);
    if (statusResult.ok) {
      setCursorAvailable(statusResult.data.cursor_agent_available);
    }
    if (defaultsResult.ok) {
      setDefaults(defaultsResult.data);
      setAudioQuery(defaultsResult.data.speech_query || "");
      setBrollQuery(defaultsResult.data.broll_query || defaultsResult.data.visual_styles[0]?.query || "");
    }
  }, []);

  useEffect(() => {
    loadDefaults();
  }, [loadDefaults]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = setInterval(async () => {
      const result = await fetchCommandJob(job.job_key);
      if (result.ok) {
        setJob(result.data);
        if (result.data.status === "completed") {
          setMessage("Short ready — preview below or open Library.");
        }
        if (["failed", "needs_review"].includes(result.data.status)) {
          setMessage(result.data.error_message || "Command failed.");
        }
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [job]);

  async function handleBuild() {
    if (busy || !backendOnline || !brollQuery.trim()) return;
    setBusy(true);
    setMessage(null);
    setJob(null);

    const command = composeMakeShortCommand({
      owner,
      audioQuery: audioQuery.trim() || undefined,
      brollQuery: brollQuery.trim(),
      instructions: instructions.trim() || undefined,
      minSeconds: defaults?.min_seconds ?? 60,
      maxSeconds: defaults?.max_seconds ?? 90,
    });

    const result = await postCommand({ command });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setJob(result.data);
    setMessage("Sent to Cursor Agent — audio search, B-roll, render, register…");
  }

  const previewPath = job?.final_output_path;
  const previewUrl = previewPath ? productionMediaUrl(previewPath) : null;
  const agentText =
    job?.agent_result || job?.stdout_log || job?.stderr_log || job?.error_message || "";
  const inProgress = job != null && ["queued", "running"].includes(job.status);

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {backendOnline === false ? (
        <BackendOfflineBanner message="Start the API in a second terminal, then refresh this page." />
      ) : null}

      {cursorAvailable === false ? (
        <p className="rounded-xl border border-amber-900/50 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          Cursor Agent CLI not detected. Install <code>agent</code> or set{" "}
          <code>CURSOR_BRIDGE_DRY_RUN=1</code> for testing.
        </p>
      ) : null}

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6">
        <h2 className="text-lg font-semibold text-zinc-100">Make motivation Short</h2>
        <p className="mt-2 text-sm text-zinc-400">
          Fields below become a Cursor Agent command — agent runs existing Python tools, checks library
          transcripts, renders 9:16 with grade + captions, then registers. Edit defaults in{" "}
          <code className="text-zinc-300">downloads/motivational/config.json</code>.
        </p>

        <div className="mt-5 space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Owner</p>
            <div className="flex gap-2">
              {(["chris", "stephen"] as MakeShortOwner[]).map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setOwner(name)}
                  className={`rounded-lg border px-3 py-1.5 text-sm capitalize ${
                    owner === name
                      ? "border-violet-500 bg-violet-500/10 text-violet-100"
                      : "border-zinc-800 bg-zinc-950 text-zinc-400"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Search for audio
            </span>
            <input
              value={audioQuery}
              onChange={(e) => setAudioQuery(e.target.value)}
              placeholder="motivational speech, podcast clip, interview excerpt…"
              className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
            <span className="mt-1 block text-xs text-zinc-500">
              Any audio type — not limited to speeches.
            </span>
          </label>

          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Visual preset</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {(defaults?.visual_styles ?? []).map((style) => (
                <button
                  key={style.id}
                  type="button"
                  onClick={() => style.query && setBrollQuery(style.query)}
                  className={`rounded-xl border px-3 py-2 text-left text-sm ${
                    brollQuery === style.query
                      ? "border-violet-500 bg-violet-500/10 text-violet-100"
                      : "border-zinc-800 bg-zinc-950 text-zinc-300"
                  }`}
                >
                  {style.label}
                </button>
              ))}
            </div>
          </div>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Visual search</span>
            <input
              value={brollQuery}
              onChange={(e) => setBrollQuery(e.target.value)}
              placeholder="luxury yacht cinematic 4k short"
              className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Instructions for Cursor
            </span>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={5}
              placeholder={`Examples:\n• Make sure the first clip is a beautiful sunset.\n• Make it ~30 seconds long — cut the speaker off smoothly at a sentence end.\n• Check audio we already have in the library — do not reuse the same transcript excerpt.`}
              className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
            <span className="mt-1 block text-xs text-zinc-500">
              Timing, first-clip rules, reuse policy, slug name — anything else agent should follow.
            </span>
          </label>

          <button
            type="button"
            disabled={busy || inProgress || backendOnline === false || !brollQuery.trim()}
            onClick={handleBuild}
            className="w-full rounded-xl bg-violet-600 py-3 text-sm font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy || inProgress ? "Running in Cursor…" : "Send to Cursor"}
          </button>
        </div>
      </section>

      {message ? <p className="text-sm text-zinc-300">{message}</p> : null}

      {job ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-300">
          <p className="font-medium capitalize text-zinc-100">
            {job.job_key} — {job.status}
          </p>
          <p className="mt-2 whitespace-pre-wrap text-zinc-400">{job.user_command}</p>
          {agentText ? (
            <pre className="mt-4 max-h-80 overflow-auto rounded-lg bg-zinc-950 p-3 text-xs text-zinc-300 whitespace-pre-wrap">
              {agentText}
            </pre>
          ) : null}
          {job.production_video_id ? (
            <Link
              href={`/library/${job.production_video_id}`}
              className="mt-3 inline-block text-sm text-violet-300 hover:underline"
            >
              Open Video {job.production_video_id} in library →
            </Link>
          ) : null}
          {previewUrl && job.status === "completed" ? (
            <div className="mt-4 flex flex-wrap items-start gap-4">
              <video src={previewUrl} controls className="aspect-[9/16] w-[200px] rounded-lg bg-zinc-950" />
              <div className="space-y-2">
                <Link href="/library" className="block text-violet-300 hover:underline">
                  View in library →
                </Link>
                <Link href="/command" className="block text-violet-300 hover:underline">
                  Command history →
                </Link>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
