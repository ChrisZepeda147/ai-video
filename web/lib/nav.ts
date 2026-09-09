import {
  BarChart3,
  Clapperboard,
  Compass,
  LayoutDashboard,
  Settings,
  Sparkles,
  Users,
  Video,
  Wrench,
  Rocket,
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
    description: "Overview and production status",
  },
  {
    href: "/discover",
    label: "Discover",
    icon: Compass,
    description: "Viral references and benchmark channels",
  },
  {
    href: "/workbench",
    label: "Workbench",
    icon: Wrench,
    description: "Quick find source or create original visuals",
  },
  {
    href: "/create",
    label: "Create",
    icon: Sparkles,
    description: "Production workspace — concepts, jobs, visuals",
  },
  {
    href: "/videos",
    label: "Videos",
    icon: Video,
    description: "Rendered videos and assets",
  },
  {
    href: "/review",
    label: "Review",
    icon: Clapperboard,
    description: "Visual and video approvals",
  },
  {
    href: "/accounts",
    label: "Accounts",
    icon: Users,
    description: "Connected publishing accounts",
  },
  {
    href: "/analytics",
    label: "Analytics",
    icon: BarChart3,
    description: "Performance across channels",
  },
  {
    href: "/pilot",
    label: "Pilot",
    icon: Rocket,
    description: "First end-to-end batch workflow",
  },
  {
    href: "/settings",
    label: "Settings",
    icon: Settings,
    description: "Preflight and configuration",
  },
];
