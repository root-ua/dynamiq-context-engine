"use client";

import { useRouter } from "next/navigation";
import { PiSignOut, PiMagnifyingGlass } from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { invalidateTokenCache } from "@/lib/api/client";
import { authClient, useSession } from "@/lib/auth-client";
import { useWorkspace } from "@/lib/workspace-context";

import { MobileNav } from "./MobileNav";
import { ThemeToggle } from "./ThemeToggle";

export function Topbar() {
  const router = useRouter();
  const { data: session } = useSession();
  const { workspace } = useWorkspace();

  async function onSignOut() {
    await authClient.signOut();
    // Drop any cached JWT so the next /login → different-user flow can't
    // race against the old token living in memory.
    invalidateTokenCache();
    void router.push("/login");
  }

  return (
    <div className="flex h-12 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur md:px-4">
      {workspace && <MobileNav workspaceSlug={workspace.slug} />}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const q = new FormData(e.currentTarget).get("q");
          if (workspace && typeof q === "string" && q.trim()) {
            void router.push(
              `/${workspace.slug}/search?q=${encodeURIComponent(q.trim())}`,
            );
          }
        }}
        className="relative max-w-md flex-1"
      >
        <PiMagnifyingGlass className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input name="q" placeholder="Search memory…" className="h-9 pl-8" />
      </form>

      <div className="ml-auto flex items-center gap-1">
        <span className="hidden max-w-[180px] truncate text-sm text-muted-foreground lg:inline">
          {session?.user?.email}
        </span>
        <ThemeToggle />
        <Button
          variant="ghost"
          size="icon"
          onClick={onSignOut}
          title="Sign out"
          aria-label="Sign out"
        >
          <PiSignOut className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
