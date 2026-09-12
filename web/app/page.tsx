import { Suspense } from "react";
import { BackendStatusBanner } from "@/components/backend-banner";
import { CommandCenterWorkspace } from "@/components/dashboard/command-center-workspace";
import { fetchCommandCenter, fetchHealth } from "@/lib/api";
import { resolveBackendProbe } from "@/lib/backend-status";

type DashboardPageProps = {
  searchParams: Promise<{ owner?: string }>;
};

export default async function DashboardPage({ searchParams }: DashboardPageProps) {
  const params = await searchParams;
  const ownerParam = (params.owner || "all").toLowerCase();
  const ownerFilter = ownerParam === "all" ? undefined : ownerParam;

  const health = await fetchHealth();
  const commandCenter = await fetchCommandCenter(
    ownerFilter ? { owner: ownerFilter } : undefined,
  );
  const backend = resolveBackendProbe(health, commandCenter);

  return (
    <>
      {!backend.online ? (
        <BackendStatusBanner
          kind="offline"
          message={health.ok ? "Health check failed." : health.message}
        />
      ) : backend.dataError ? (
        <BackendStatusBanner kind="error" message={backend.dataError} />
      ) : null}

      {commandCenter.ok ? (
        <Suspense fallback={<p className="text-sm text-zinc-500">Loading command center…</p>}>
          <CommandCenterWorkspace initial={commandCenter.data} initialOwner={ownerParam} />
        </Suspense>
      ) : (
        <p className="text-sm text-red-300">{commandCenter.message}</p>
      )}
    </>
  );
}
