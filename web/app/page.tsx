import { BackendOfflineBanner } from "@/components/backend-banner";
import { PageHeader } from "@/components/page-header";
import { PlatformBadge } from "@/components/platform-badge";
import { SectionHeader } from "@/components/section-header";
import { StatCard } from "@/components/stat-card";
import { StatusBadge } from "@/components/status-badge";
import { fetchDiscoveryStats, fetchDiscoveryTop } from "@/lib/api";
import { buildDashboardStats, formatReferenceViews } from "@/lib/dashboard-stats";
import { accountChannels, productionQueue } from "@/lib/demo-data";
import type { ReferenceItem } from "@/lib/types";

function ViralityBadge({ score }: { score: number | null | undefined }) {
  if (score == null) {
    return (
      <span className="inline-flex rounded-md bg-zinc-700/40 px-2 py-0.5 text-xs text-zinc-400">
        —
      </span>
    );
  }
  const tone =
    score >= 90
      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
      : score >= 80
        ? "bg-violet-500/15 text-violet-300 ring-violet-500/30"
        : "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30";

  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${tone}`}
    >
      {Math.round(score)}
    </span>
  );
}

function ReferenceTable({ items }: { items: ReferenceItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 px-6 py-10 text-center text-sm text-zinc-500">
        No references in the catalog yet. Run discovery ingest to populate data.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800">
      <table className="min-w-full divide-y divide-zinc-800">
        <thead className="bg-zinc-900/80">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">
              Title
            </th>
            <th className="hidden px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-zinc-500 md:table-cell">
              Channel
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">
              Niche
            </th>
            <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-zinc-500">
              Views
            </th>
            <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-zinc-500">
              Score
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800 bg-zinc-900/30">
          {items.map((ref) => (
            <tr key={ref.id} className="hover:bg-zinc-900/60">
              <td className="max-w-[220px] truncate px-4 py-3 text-sm font-medium text-zinc-200">
                {ref.title}
              </td>
              <td className="hidden px-4 py-3 text-sm text-zinc-400 md:table-cell">
                {ref.channel ?? "—"}
              </td>
              <td className="px-4 py-3 text-sm capitalize text-zinc-400">
                {ref.niches[0]?.niche ?? "—"}
              </td>
              <td className="px-4 py-3 text-right text-sm tabular-nums text-zinc-300">
                {formatReferenceViews(ref.view_count)}
              </td>
              <td className="px-4 py-3 text-right">
                <ViralityBadge score={ref.virality_score} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function DashboardPage() {
  const [statsResult, topResult] = await Promise.all([
    fetchDiscoveryStats(),
    fetchDiscoveryTop({ min_score: 0, limit: 5 }),
  ]);

  const discoveryOffline = !statsResult.ok;
  const stats = statsResult.ok ? statsResult.data : null;
  const topReferences = topResult.ok ? topResult.data.items : [];
  const dashboardStats = buildDashboardStats(stats);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Live discovery metrics from the Python catalog. Production queue and account sections remain demo data until those pipelines are connected."
      />

      {discoveryOffline ? (
        <BackendOfflineBanner
          message={
            statsResult.ok === false
              ? statsResult.message
              : "Discovery backend is offline."
          }
        />
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {dashboardStats.map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </section>

      <div className="mt-10 grid gap-8 xl:grid-cols-2">
        <section>
          <SectionHeader
            title="Recent Viral References"
            description={
              topResult.ok
                ? "Top references from discovery catalog (live)"
                : "Unable to load live references"
            }
          />
          <ReferenceTable items={topReferences} />
        </section>

        <section>
          <SectionHeader
            title="Production Queue"
            description="Demo pipeline states — render integration coming later"
          />
          <div className="space-y-3">
            {productionQueue.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-zinc-200">
                    {item.title}
                  </p>
                  <p className="text-xs text-zinc-500">{item.niche}</p>
                </div>
                <StatusBadge state={item.state} />
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="mt-10">
        <SectionHeader
          title="Account Overview"
          description="Demo accounts — publishing integration coming later"
        />
        <div className="grid gap-4 md:grid-cols-2">
          {accountChannels.map((account) => (
            <div
              key={account.id}
              className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="font-medium text-zinc-100">{account.name}</h3>
                  <p className="mt-1 text-sm text-zinc-500">{account.niche}</p>
                </div>
                <div className="text-right text-xs text-zinc-500">
                  <p>
                    <span className="font-medium text-zinc-300">
                      {account.postsToday}
                    </span>{" "}
                    posts today
                  </p>
                  <p className="mt-1">
                    <span className="font-medium text-zinc-300">
                      {account.scheduled}
                    </span>{" "}
                    scheduled
                  </p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {account.platforms.map((platform) => (
                  <PlatformBadge key={platform} platform={platform} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
