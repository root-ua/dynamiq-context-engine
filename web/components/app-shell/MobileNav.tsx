"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PiList, PiX } from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

import { getNavGroups, isActive } from "./nav-config";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

export function MobileNav({ workspaceSlug }: { workspaceSlug: string }) {
  const [open, setOpen] = React.useState(false);
  const pathname = usePathname();
  const base = `/${workspaceSlug}`;
  const groups = getNavGroups(workspaceSlug);

  // Close the drawer automatically when the route changes.
  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open navigation"
        >
          <PiList className="h-5 w-5" />
        </Button>
      </DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            "fixed inset-y-0 left-0 z-50 flex w-[280px] max-w-[85vw] flex-col border-r bg-background shadow-xl",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left",
            "duration-200",
          )}
        >
          <DialogPrimitive.Title className="sr-only">
            Navigation
          </DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Workspace navigation menu.
          </DialogPrimitive.Description>
          <div className="flex items-center justify-between p-3">
            <div className="flex-1">
              <WorkspaceSwitcher />
            </div>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close navigation">
                <PiX className="h-4 w-4" />
              </Button>
            </DialogPrimitive.Close>
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
                        onClick={() => setOpen(false)}
                        className={cn(
                          "relative flex h-9 items-center gap-2 rounded-md pl-3 pr-2 transition-colors",
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
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
