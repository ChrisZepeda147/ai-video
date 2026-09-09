import { Suspense } from "react";
import { BackendOfflineBanner } from "@/components/backend-banner";
import { DiscoverActions } from "@/components/discover/discover-actions";
import { DiscoverFilters } from "@/components/discover/discover-filters";
import { ReferenceListInteractive } from "@/components/discover/reference-list-interactive";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import {
  fetchDiscoveryNiches,
  fetchDiscoveryReferences,
  fetchDiscoveryStats,
} from "@/lib/api";

type DiscoverPageProps = {
  searchParams: Promise<{
    niche?: string;
    min_score?: string;
    search?: string;
    limit?: string;
    status?: string;
  }>;
};

export default async function DiscoverPage({ searchParams }: DiscoverPageProps) {
  const params = await searchParams;
  const niche = params.niche?.trim() || undefined;
  const search = params.search?.trim() || undefined;
  const status = params.status?.trim() || undefined;
  const minScore = Number(params.min_score ?? "0");
  const limit = Number(params.limit ?? "25");

  const [statsResult, referencesResult, nichesResult] = await Promise.all([
    fetchDiscoveryStats(),
    fetchDiscoveryReferences({
      niche,
      min_score: Number.isFinite(minScore) ? minScore : 0,
      limit: Number.isFinite(limit) ? Math.min(Math.max(limit, 1), 200) : 25,
      search,
      status,
    }),
    fetchDiscoveryNiches(),
  ]);

  const offline = !statsResult.ok || !referencesResult.ok;
  const offlineMessage =
    (!statsResult.ok && statsResult.message) ||
    (!referencesResult.ok && referencesResult.message) ||
    "Discovery backend is offline.";

  const stats = statsResult.ok ? statsResult.data : null;
  const references = referencesResult.ok ? referencesResult.data.items : [];
  const niches = nichesResult.ok ? nichesResult.data.items : [];

  return (
    <>
      <PageHeader
        title="Discover"
        description="Scan YouTube for viral reference metadata, analyze Creative DNA, and generate original concept ideas. References are never production assets."
      />

      {offline ? <BackendOfflineBanner message={offlineMessage} /> : null}

      {!offline ? <DiscoverActions niches={niches} /> : null}

      {stats ? (
        <section className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Total references" value={stats.total_references} hint="Metadata catalog" live />
          <StatCard label="Added today" value={stats.references_added_today} hint="New discoveries" live />
          <StatCard label="High virality" value={stats.high_virality_references} hint="Score ≥ 70" live />
          <StatCard label="Searches today" value={stats.searches_today} hint="Discovery runs" live />
        </section>
      ) : null}

      <Suspense
        fallback={
          <div className="mb-6 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
            Loading filters…
          </div>
        }
      >
        <DiscoverFilters
          niches={niches}
          defaults={{
            niche: params.niche,
            min_score: params.min_score ?? "0",
            search: params.search,
            limit: params.limit ?? "25",
            status: params.status,
          }}
        />
      </Suspense>

      <section className="mt-8">
        <p className="mb-4 text-sm text-zinc-500">
          {referencesResult.ok
            ? `${references.length} reference${references.length === 1 ? "" : "s"}`
            : "Unable to load references"}
        </p>
        <ReferenceListInteractive items={references} />
      </section>
    </>
  );
}
