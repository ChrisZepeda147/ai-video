import type { DashboardStatCard } from "@/lib/dashboard-stats";

export function StatCard({ label, value, hint, trend, live }: DashboardStatCard) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-zinc-400">{label}</p>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            live
              ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30"
              : "bg-zinc-700/40 text-zinc-500 ring-1 ring-zinc-600/40"
          }`}
        >
          {live ? "Live" : "Demo"}
        </span>
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-zinc-500">{hint}</p> : null}
      {trend ? (
        <p className="mt-3 text-xs font-medium text-violet-400">{trend}</p>
      ) : null}
    </div>
  );
}
