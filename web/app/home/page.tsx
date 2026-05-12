"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/lib/auth-client";
import { useWorkspace } from "@/lib/workspace-context";

export default function HomeRedirect() {
  const router = useRouter();
  const { data: session, isPending } = useSession();
  const { workspaces, workspace, isLoading } = useWorkspace();

  useEffect(() => {
    if (isPending || isLoading) return;

    if (!session?.user) {
      void router.replace("/login");
      return;
    }
    if (workspaces.length === 0) {
      void router.replace("/onboarding");
      return;
    }
    const target = workspace ?? workspaces[0]!;
    void router.replace(`/${target.slug}`);
  }, [session, workspace, workspaces, isPending, isLoading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
      Loading workspace…
    </div>
  );
}
