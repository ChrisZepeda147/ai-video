import type { ProductionQueueItem } from "@/lib/demo-data";

const stateStyles: Record<
  ProductionQueueItem["state"],
  { label: string; className: string }
> = {
  concept: {
    label: "Concept",
    className: "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30",
  },
  "generating visuals": {
    label: "Generating visuals",
    className: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  },
  rendering: {
    label: "Rendering",
    className: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  },
  "waiting review": {
    label: "Waiting review",
    className: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  },
  approved: {
    label: "Approved",
    className: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  },
};

export function StatusBadge({ state }: { state: ProductionQueueItem["state"] }) {
  const style = stateStyles[state];
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style.className}`}
    >
      {style.label}
    </span>
  );
}
