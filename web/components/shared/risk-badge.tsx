const LEVELS: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  yellow: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  orange: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  red: "bg-red-500/15 text-red-300 ring-red-500/30",
};

export function RiskBadge({
  label,
  score,
  level,
}: {
  label: string;
  score: number;
  level: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${LEVELS[level] || LEVELS.yellow}`}
      title={`${label}: ${Math.round(score)}`}
    >
      {label}: {Math.round(score)}
    </span>
  );
}

export function riskLevel(score: number, invert = false): string {
  const value = invert ? 100 - score : score;
  if (value >= 75) return "green";
  if (value >= 50) return "yellow";
  if (value >= 25) return "orange";
  return "red";
}
