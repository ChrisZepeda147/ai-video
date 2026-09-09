export type StatCard = {
  label: string;
  value: string | number;
  hint?: string;
  trend?: string;
};

export type ViralReference = {
  id: string;
  title: string;
  channel: string;
  niche: string;
  views: number;
  viralityScore: number;
};

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

export const dashboardStats: StatCard[] = [
  { label: "Viral References", value: 248, hint: "Metadata catalog", trend: "+12 this week" },
  { label: "Concepts Ready", value: 36, hint: "Awaiting visuals", trend: "+8 today" },
  { label: "Visuals Waiting Review", value: 14, hint: "Human approval queue" },
  { label: "Videos Ready", value: 9, hint: "Approved for publish" },
  { label: "Connected Accounts", value: 4, hint: "YouTube, TikTok, Instagram" },
  { label: "Posts Today", value: 6, hint: "Across all channels", trend: "2 scheduled" },
];

export const recentViralReferences: ViralReference[] = [
  {
    id: "ref-1",
    title: "Don't stop driving at 2AM (true story)",
    channel: "NightDrive Stories",
    niche: "Horror",
    views: 2_400_000,
    viralityScore: 91,
  },
  {
    id: "ref-2",
    title: "The parking garage level that doesn't exist",
    channel: "Urban Fear",
    niche: "Horror",
    views: 1_850_000,
    viralityScore: 87,
  },
  {
    id: "ref-3",
    title: "She texted me from a number that wasn't hers",
    channel: "Message Horror",
    niche: "Relationship",
    views: 3_100_000,
    viralityScore: 93,
  },
  {
    id: "ref-4",
    title: "What billionaires do before 5AM",
    channel: "Success Lens",
    niche: "Luxury",
    views: 980_000,
    viralityScore: 78,
  },
  {
    id: "ref-5",
    title: "The crossover that broke the internet",
    channel: "Court Clips",
    niche: "Basketball",
    views: 4_200_000,
    viralityScore: 95,
  },
];

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
