type Platform = "youtube" | "tiktok" | "instagram";

const platformStyles: Record<Platform, { label: string; className: string }> = {
  youtube: {
    label: "YouTube",
    className: "bg-red-500/15 text-red-300 ring-red-500/30",
  },
  tiktok: {
    label: "TikTok",
    className: "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
  },
  instagram: {
    label: "Instagram",
    className: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  },
};

export function PlatformBadge({ platform }: { platform: Platform }) {
  const style = platformStyles[platform];
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style.className}`}
    >
      {style.label}
    </span>
  );
}
