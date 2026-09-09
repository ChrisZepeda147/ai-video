"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { NicheCoverageItem } from "@/lib/types";

type DiscoverFiltersProps = {
  niches: NicheCoverageItem[];
  defaults: {
    niche?: string;
    min_score?: string;
    search?: string;
    limit?: string;
    status?: string;
  };
};

export function DiscoverFilters({ niches, defaults }: DiscoverFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const params = new URLSearchParams(searchParams.toString());

    for (const key of ["niche", "min_score", "search", "limit", "status"]) {
      const value = String(form.get(key) ?? "").trim();
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    }

    router.push(`/discover?${params.toString()}`);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="grid gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 md:grid-cols-2 xl:grid-cols-5"
    >
      <label className="block text-sm">
        <span className="mb-1 block text-zinc-400">Niche</span>
        <select
          name="niche"
          defaultValue={defaults.niche ?? ""}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
        >
          <option value="">All niches</option>
          {niches.map((item) => (
            <option key={item.niche} value={item.niche}>
              {item.niche} ({item.reference_count})
            </option>
          ))}
        </select>
      </label>

      <label className="block text-sm">
        <span className="mb-1 block text-zinc-400">Min virality score</span>
        <input
          type="number"
          name="min_score"
          min={0}
          max={100}
          step={1}
          defaultValue={defaults.min_score ?? "0"}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
        />
      </label>

      <label className="block text-sm md:col-span-2 xl:col-span-1">
        <span className="mb-1 block text-zinc-400">Search title / channel</span>
        <input
          type="search"
          name="search"
          defaultValue={defaults.search ?? ""}
          placeholder="e.g. foggy road"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
        />
      </label>

      <label className="block text-sm">
        <span className="mb-1 block text-zinc-400">Status</span>
        <select
          name="status"
          defaultValue={defaults.status ?? ""}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
        >
          <option value="">Any</option>
          <option value="active">Active</option>
          <option value="exhausted">Exhausted</option>
          <option value="analyzed">Analyzed</option>
          <option value="unanalyzed">Unanalyzed</option>
        </select>
      </label>

      <label className="block text-sm">
        <span className="mb-1 block text-zinc-400">Limit</span>
        <input
          type="number"
          name="limit"
          min={1}
          max={200}
          defaultValue={defaults.limit ?? "25"}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
        />
      </label>

      <div className="flex items-end md:col-span-2 xl:col-span-5">
        <button
          type="submit"
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
        >
          Apply filters
        </button>
      </div>
    </form>
  );
}
