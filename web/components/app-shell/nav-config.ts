import {
  PiPulse,
  PiCalendarBlank,
  PiCheckSquareOffset,
  PiCpu,
  PiCubeTransparent,
  PiFileText,
  PiGear,
  PiGraph,
  PiHouse,
  PiKey,
  PiLightning,
  PiMagnifyingGlass,
  PiPlugs,
  PiShapes,
} from "react-icons/pi";

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export function getNavGroups(workspaceSlug: string): NavGroup[] {
  const base = `/${workspaceSlug}`;
  return [
    {
      label: "Overview",
      items: [
        { href: base, label: "Home", icon: PiHouse },
        { href: `${base}/search`, label: "Search", icon: PiMagnifyingGlass },
      ],
    },
    {
      label: "Memory",
      items: [
        { href: `${base}/documents`, label: "Documents", icon: PiFileText },
        {
          href: `${base}/entities`,
          label: "Entities",
          icon: PiCubeTransparent,
        },
        { href: `${base}/graph`, label: "Graph", icon: PiGraph },
        { href: `${base}/episodes`, label: "Episodes", icon: PiCalendarBlank },
        { href: `${base}/sources`, label: "Sources", icon: PiPlugs },
      ],
    },
    {
      label: "Schema",
      items: [{ href: `${base}/ontology`, label: "Ontology", icon: PiShapes }],
    },
    {
      label: "Governance",
      items: [
        {
          href: `${base}/review`,
          label: "Review queue",
          icon: PiCheckSquareOffset,
        },
        {
          href: `${base}/actions`,
          label: "Actions",
          icon: PiLightning,
        },
      ],
    },
    {
      label: "Agents",
      items: [
        { href: `${base}/agent`, label: "Agent console", icon: PiCpu },
        {
          href: `${base}/settings/integrations`,
          label: "Connect agents",
          icon: PiKey,
        },
        { href: `${base}/activity`, label: "Activity", icon: PiPulse },
      ],
    },
    {
      label: "Workspace",
      items: [{ href: `${base}/settings`, label: "Settings", icon: PiGear }],
    },
  ];
}

export function isActive(
  pathname: string | null | undefined,
  item: NavItem,
  basePath: string,
): boolean {
  if (!pathname) return false;
  if (item.href === basePath) return pathname === basePath;
  return pathname.startsWith(item.href);
}
