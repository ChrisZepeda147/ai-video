import type { DiscoveryStats } from "@/lib/types";
import { formatViews } from "@/lib/demo-data";

export type DashboardStatCard = {
  label: string;
  value: string | number;
  hint?: string;
  trend?: string;
  live: boolean;
};

const PLACEHOLDER_STATS: DashboardStatCard[] = [
  {
    label: "Videos Ready",
    value: 9,
    hint: "Approved for publish",
    live: false,
  },
  {
    label: "Connected Accounts",
    value: 4,
    hint: "YouTube, TikTok, Instagram",
    live: false,
  },
  {
    label: "Posts Today",
    value: 6,
    hint: "Across all channels",
    trend: "2 scheduled",
    live: false,
  },
];

export function buildDashboardStats(
  discovery: DiscoveryStats | null,
): DashboardStatCard[] {
  const liveStats: DashboardStatCard[] = discovery
    ? [
        {
          label: "Viral References",
          value: discovery.total_references,
          hint: "Metadata catalog",
          trend:
            discovery.references_added_today > 0
              ? `+${discovery.references_added_today} today`
              : undefined,
          live: true,
        },
        {
          label: "Concepts Ready",
          value: discovery.concepts_ready,
          hint: "Generated / shortlisted / approved",
          live: true,
        },
        {
          label: "Visuals Waiting Review",
          value: discovery.visuals_waiting_review,
          hint: "Human approval queue",
          live: true,
        },
      ]
    : [
        {
          label: "Viral References",
          value: "—",
          hint: "Start discovery backend",
          live: false,
        },
        {
          label: "Concepts Ready",
          value: "—",
          hint: "Start discovery backend",
          live: false,
        },
        {
          label: "Visuals Waiting Review",
          value: "—",
          hint: "Start discovery backend",
          live: false,
        },
      ];

  return [...liveStats, ...PLACEHOLDER_STATS];
}

export function formatReferenceViews(views: number | null | undefined): string {
  if (views == null) return "—";
  return formatViews(views);
}
