"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchPreflight } from "@/lib/api";
import type { PreflightResponse } from "@/lib/types";

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "ready"
      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
      : status === "warning"
        ? "bg-amber-500/15 text-amber-300 ring-amber-500/30"
        : "bg-red-500/15 text-red-300 ring-red-500/30";
  const label = status === "ready" ? "READY" : status === "warning" ? "WARNING" : "NOT CONFIGURED";
  return (
    <span className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-bold ring-1 ring-inset ${tone}`}>
      {label}
    </span>
  );
}

export function PreflightPanel() {
  const [data, setData] = useState<PreflightResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchPreflight();
    setLoading(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setData(result.data);
    setError(null);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <p className="text-sm text-zinc-500">Running preflight checks…</p>;
  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!data) return null;

  const groupTitles: Record<string, string> = {
    core: "Core",
    ai_media: "AI / Media",
    publishing: "Publishing",
    analytics: "Analytics",
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div>
          <p className="text-xs text-zinc-500">Pilot readiness</p>
          <p className="text-lg font-semibold text-zinc-100">
            {data.summary.pilot_ready ? "Core systems OK" : "Core gaps — fix before live pilot"}
          </p>
        </div>
        <div className="flex gap-3 text-xs text-zinc-400">
          <span className="text-emerald-300">{data.summary.ready} ready</span>
          <span className="text-amber-300">{data.summary.warning} warning</span>
          <span className="text-red-300">{data.summary.not_configured} not configured</span>
        </div>
        <button type="button" onClick={load} className="ml-auto rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300">
          Re-check
        </button>
      </div>

      {Object.entries(data.groups).map(([key, checks]) => (
        <section key={key} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h3 className="text-sm font-semibold text-zinc-200">{groupTitles[key] ?? key}</h3>
          <ul className="mt-3 space-y-2">
            {checks.map((check) => (
              <li key={check.label} className="flex items-start gap-3 rounded-lg border border-zinc-800/60 px-3 py-2">
                <StatusBadge status={check.status} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-zinc-200">{check.label}</p>
                  <p className="text-xs text-zinc-500">{check.detail}</p>
                  {check.fix_hint ? (
                    <p className="mt-1 text-xs text-violet-300/80">{check.fix_hint}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
