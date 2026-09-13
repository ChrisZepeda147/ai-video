"use client";

export type FinishedBucketFilterValue = "unused" | "used" | "all";

export function FinishedBucketFilter({
  value,
  onChange,
  unusedCount,
  usedCount,
}: {
  value: FinishedBucketFilterValue;
  onChange: (next: FinishedBucketFilterValue) => void;
  unusedCount: number;
  usedCount: number;
}) {
  const options: Array<{ id: FinishedBucketFilterValue; label: string; count: number }> = [
    { id: "unused", label: "Unused", count: unusedCount },
    { id: "used", label: "Used", count: usedCount },
    { id: "all", label: "All", count: unusedCount + usedCount },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => onChange(option.id)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
              active
                ? "border-violet-600 bg-violet-600/20 text-violet-100"
                : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
            }`}
          >
            {option.label}
            <span className="ml-1.5 text-[10px] opacity-70">{option.count}</span>
          </button>
        );
      })}
    </div>
  );
}

export function FinishedBucketBadge({ used }: { used: boolean }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
        used
          ? "border-emerald-800 bg-emerald-950/50 text-emerald-200"
          : "border-amber-800 bg-amber-950/40 text-amber-200"
      }`}
    >
      {used ? "Used folder" : "Unused folder"}
    </span>
  );
}
