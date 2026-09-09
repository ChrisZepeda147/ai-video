"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { postDiscoveryDiscover, postDiscoveryScan } from "@/lib/api";
import type { NicheCoverageItem } from "@/lib/types";

export function DiscoverActions({ niches }: { niches: NicheCoverageItem[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [niche, setNiche] = useState("");
  const [limit, setLimit] = useState("25");
  const [maxSearches, setMaxSearches] = useState("10");
  const [loading, setLoading] = useState<"scan" | "discover" | null>(null);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  async function handleScan(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim() || loading) return;
    setLoading("scan");
    setMessage(null);
    const result = await postDiscoveryScan({
      query: query.trim(),
      niche: niche || undefined,
      limit: Number(limit) || 25,
    });
    setLoading(null);
    if (!result.ok) {
      setMessage({ type: "err", text: result.message });
      return;
    }
    const d = result.data;
    if (d.skipped_cooldown) {
      setMessage({ type: "err", text: "Search skipped (cooldown). Use force in CLI or wait." });
    } else {
      setMessage({
        type: "ok",
        text: `Found ${d.ids_found} · New ${d.ids_new} · Updated ${d.ids_updated} · Existing ${d.ids_existing} · Detail requests ${d.detail_requests}`,
      });
    }
    router.refresh();
  }

  async function handleDiscoverAll() {
    if (loading) return;
    setLoading("discover");
    setMessage(null);
    const result = await postDiscoveryDiscover({
      max_searches: Number(maxSearches) || 10,
    });
    setLoading(null);
    if (!result.ok) {
      setMessage({ type: "err", text: result.message });
      return;
    }
    const d = result.data;
    setMessage({
      type: "ok",
      text: `Ran ${d.searches_executed} searches · New ${d.ids_new} · Updated ${d.ids_updated} · Detail requests ${d.detail_requests}`,
    });
    router.refresh();
  }

  return (
    <section className="mb-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-sm font-semibold text-zinc-200">Run discovery</h2>
      <p className="mt-1 text-xs text-zinc-500">
        Metadata-only YouTube search. References are never production assets.
      </p>

      <form onSubmit={handleScan} className="mt-4 grid gap-3 md:grid-cols-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search query e.g. scary story"
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 md:col-span-2"
          disabled={loading !== null}
        />
        <select
          value={niche}
          onChange={(e) => setNiche(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          disabled={loading !== null}
        >
          <option value="">Niche (optional)</option>
          {niches.map((n) => (
            <option key={n.niche} value={n.niche}>
              {n.niche}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={1}
          max={100}
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          disabled={loading !== null}
          title="Result limit"
        />
        <button
          type="submit"
          disabled={loading !== null || !query.trim()}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50 md:col-span-2"
        >
          {loading === "scan" ? "Scanning…" : "Scan YouTube"}
        </button>
      </form>

      <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-zinc-800 pt-4">
        <label className="text-sm text-zinc-400">
          Max searches
          <input
            type="number"
            min={1}
            max={50}
            value={maxSearches}
            onChange={(e) => setMaxSearches(e.target.value)}
            className="ml-2 w-16 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1 text-zinc-100"
            disabled={loading !== null}
          />
        </label>
        <button
          type="button"
          onClick={handleDiscoverAll}
          disabled={loading !== null}
          className="rounded-lg border border-violet-500/40 bg-violet-600/20 px-4 py-2 text-sm font-medium text-violet-200 hover:bg-violet-600/30 disabled:opacity-50"
        >
          {loading === "discover" ? "Discovering…" : "Discover All Niches"}
        </button>
      </div>

      {message ? (
        <p
          className={`mt-4 text-sm ${message.type === "ok" ? "text-emerald-400" : "text-amber-300"}`}
        >
          {message.text}
        </p>
      ) : null}
    </section>
  );
}
