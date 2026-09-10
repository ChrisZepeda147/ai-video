export type ProductionQueueItem = {
  id: string;
  title: string;
  niche: string;
  state:
    | "concept"
    | "generating visuals"
    | "rendering"
    | "waiting review"
    | "approved";
};

export type AccountChannel = {
  id: string;
  name: string;
  niche: string;
  platforms: ("youtube" | "tiktok" | "instagram")[];
  postsToday: number;
  scheduled: number;
};

export const productionQueue: ProductionQueueItem[] = [
  {
    id: "pq-1",
    title: "Foggy mountain road — isolation hook",
    niche: "Horror",
    state: "generating visuals",
  },
  {
    id: "pq-2",
    title: "Empty train car at midnight",
    niche: "Horror",
    state: "waiting review",
  },
  {
    id: "pq-3",
    title: "Luxury penthouse rain scene",
    niche: "Luxury",
    state: "rendering",
  },
  {
    id: "pq-4",
    title: "Breakup texts escalation",
    niche: "Relationship",
    state: "concept",
  },
  {
    id: "pq-5",
    title: "Parking garage echo footsteps",
    niche: "Horror",
    state: "approved",
  },
];

export const accountChannels: AccountChannel[] = [
  {
    id: "acc-1",
    name: "Luxury / Success",
    niche: "Luxury",
    platforms: ["youtube", "tiktok", "instagram"],
    postsToday: 2,
    scheduled: 3,
  },
  {
    id: "acc-2",
    name: "Relationships",
    niche: "Relationship",
    platforms: ["tiktok", "instagram"],
    postsToday: 1,
    scheduled: 2,
  },
  {
    id: "acc-3",
    name: "Horror",
    niche: "Horror",
    platforms: ["youtube", "tiktok"],
    postsToday: 2,
    scheduled: 4,
  },
  {
    id: "acc-4",
    name: "Basketball",
    niche: "Basketball",
    platforms: ["youtube", "instagram"],
    postsToday: 1,
    scheduled: 1,
  },
];

export function formatViews(views: number): string {
  if (views >= 1_000_000) {
    return `${(views / 1_000_000).toFixed(1)}M`;
  }
  if (views >= 1_000) {
    return `${(views / 1_000).toFixed(0)}K`;
  }
  return String(views);
}
