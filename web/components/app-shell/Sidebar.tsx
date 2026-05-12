"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/Logo";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

import { getNavGroups, isActive } from "./nav-config";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

export function Sidebar({ workspaceSlug }: { workspaceSlug: string }) {
  const pathname = usePathname();
  const base = `/${workspaceSlug}`;
  const groups = getNavGroups(workspaceSlug);

  return (
    <aside className="hidden w-[260px] shrink-0 flex-col border-r bg-background/50 md:flex">
      <div className="p-3">
        <WorkspaceSwitcher />
      </div>
      <Separator />
      <nav className="flex-1 overflow-y-auto p-2 text-sm">
        {groups.map((group) => (
          <div key={group.label} className="mb-4">
            <div className="px-2 pb-1 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(pathname, item, base);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "relative flex h-8 items-center gap-2 rounded-md pl-3 pr-2 transition-colors",
                      active
                        ? "bg-accent font-medium text-accent-foreground before:absolute before:left-0 before:top-1/2 before:h-4 before:w-0.5 before:-translate-y-1/2 before:rounded-full before:bg-brand"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <Separator />
      <div className="p-3 text-xs text-muted-foreground">
        <Logo className="text-xs" subtitle="Context Engine" />
      </div>
    </aside>
  );
}
