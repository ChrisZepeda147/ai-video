"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import {
  fetchHealth,
  fetchShortBuildDefaults,
  fetchShortBuildStatus,
  postBuildShort,
  productionMediaUrl,
} from "@/lib/api";
import type { ShortBuildDefaults, ShortBuildJob } from "@/lib/types";

export function MakeShortWorkspace() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [defaults, setDefaults] = useState<ShortBuildDefaults | null>(null);
  const [speechQuery, setSpeechQuery] = useState("");
  const [brollQuery, setBrollQuery] = useState("");
  const [slug, setSlug] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<ShortBuildJob | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadDefaults = useCallback(async () => {
    const health = await fetchHealth();
    setBackendOnline(health.ok);
    if (!health.ok) return;
    const result = await fetchShortBuildDefaults();
    if (result.ok) {
      setDefaults(result.data);
      setSpeechQuery(result.data.speech_query || "");
      setBrollQuery(result.data.broll_query || result.data.visual_styles[0]?.query || "");
    }
  }, []);

  useEffect(() => {
    loadDefaults();
  }, [loadDefaults]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = setInterval(async () => {
      const result = await fetchShortBuildStatus(job.job_id);
      if (result.ok) {
        setJob(result.data);
        if (result.data.status === "completed") {
          setMessage("Short ready — preview below or open Videos.");
        }
        if (result.data.status === "failed") {
          setMessage(result.data.error || "Build failed.");
        }
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [job]);

  async function handleBuild() {
    if (busy || !backendOnline || !brollQuery.trim()) return;
    setBusy(true);
    setMessage(null);
    setJob(null);
    const result = await postBuildShort({
      slug: slug.trim() || undefined,
      speech_query: speechQuery.trim() || undefined,
      broll_query: brollQuery.trim(),
      min_seconds: defaults?.min_seconds ?? 60,
      max_seconds: defaults?.max_seconds ?? 90,
      segment_length: defaults?.segment_length ?? 8,
      apply_grade: true,
      register_site: true,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setJob(result.data);
    setMessage("Running Stephen's mix script — speech + B-roll search, renders 9:16 Short…");
  }

  const previewUrl = job?.output_path
    ? productionMediaUrl(job.output_path)
    : job?.preview_url
      ? productionMediaUrl(job.preview_url.replace(/^\/media\//, ""))
      : null;
  const inProgress = job != null && ["queued", "running"].includes(job.status);

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {backendOnline === false ? (
        <BackendOfflineBanner message="Start the API in a second terminal, then refresh this page." />
      ) : null}

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6">
        <h2 className="text-lg font-semibold text-zinc-100">Make motivation Short</h2>
        <p className="mt-2 text-sm text-zinc-400">
          Same one-shot Python job Stephen used in Cursor: search speech + B-roll, mix, grade, word captions. Prior usage is advisory.
          Edit defaults in <code className="text-zinc-300">downloads/motivational/config.json</code>.
        </p>

        <div className="mt-5 space-y-4">
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Speech search</span>
            <input
              value={speechQuery}
              onChange={(e) => setSpeechQuery(e.target.value)}
              placeholder="motivational speech discipline mindset"
              className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
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
            <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">Slug (optional)</span>
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="yacht-motivation"
              className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
          </label>

          <button
            type="button"
            disabled={busy || inProgress || backendOnline === false || !brollQuery.trim()}
            onClick={handleBuild}
            className="w-full rounded-xl bg-violet-600 py-3 text-sm font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy || inProgress ? "Building…" : "Build Short"}
          </button>
        </div>
      </section>

      {message ? <p className="text-sm text-zinc-300">{message}</p> : null}

      {job ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-300">
          <p className="font-medium capitalize text-zinc-100">Status: {job.status}</p>
          {job.error ? <p className="mt-2 text-red-400">{job.error}</p> : null}
          {previewUrl && job.status === "completed" ? (
            <div className="mt-4 flex flex-wrap items-start gap-4">
              <video src={previewUrl} controls className="aspect-[9/16] w-[200px] rounded-lg bg-zinc-950" />
              <div className="space-y-2">
                <Link href="/videos" className="block text-violet-300 hover:underline">
                  View in library →
                </Link>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
