import {
  BarChart3,
  CalendarDays,
  Clapperboard,
  LayoutDashboard,
  MessageSquare,
  Settings,
  Sparkles,
  Users,
  Video,
  Library,
  LayoutGrid,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  description?: string;
};

export const navItems: NavItem[] = [
  {
    href: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Daily command center",
  },
  {
    href: "/command",
    label: "Command",
    icon: MessageSquare,
    description: "Natural-language Cursor commands",
  },
  {
    href: "/library",
    label: "Library",
    icon: Library,
    description: "Production videos and components",
  },
  {
    href: "/combinations",
    label: "Combinations",
    icon: LayoutGrid,
    description: "Audio + visual pairing board",
  },
  {
    href: "/create",
    label: "Make Short",
    icon: Sparkles,
    description: "Structured brief → Cursor Agent Short",
  },
  {
    href: "/weekly",
    label: "Weekly",
    icon: CalendarDays,
    description: "Sunday feed → 7am daily 3-video runs",
  },
  {
    href: "/videos",
    label: "Videos",
    icon: Video,
    description: "Rendered Shorts dashboard",
  },
  {
    href: "/review",
    label: "Review",
    icon: Clapperboard,
    description: "Approve before publishing",
  },
  {
    href: "/accounts",
    label: "Accounts",
    icon: Users,
    description: "YouTube, TikTok, Instagram, Facebook — Stephen or Chris",
  },
  {
    href: "/analytics",
    label: "Analytics",
    icon: BarChart3,
    description: "Per-owner platform analytics",
  },
  {
    href: "/settings",
    label: "Settings",
    icon: Settings,
    description: "Preflight and configuration",
  },
];

/** Hidden routes kept for power users / legacy links */
export const secondaryNavItems: NavItem[] = [
  { href: "/discover", label: "Discover", icon: LayoutDashboard, description: "Viral reference research" },
  { href: "/workbench", label: "Workbench", icon: LayoutDashboard, description: "Discovery find + Cursor generation" },
  { href: "/pilot", label: "Pilot", icon: LayoutDashboard, description: "Batch workflow" },
];
