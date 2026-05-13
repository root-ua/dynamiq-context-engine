"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Sidebar } from "@/components/app-shell/Sidebar";
import { Topbar } from "@/components/app-shell/Topbar";
import { useWorkspace } from "@/lib/workspace-context";

export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const params = useParams();
  const slug = typeof params.workspace === "string" ? params.workspace : "";
  const { workspaces, workspace, setWorkspaceId, isLoading } = useWorkspace();

  useEffect(() => {
    if (isLoading) return;
    if (workspaces.length === 0) {
      void router.replace("/onboarding");
      return;
    }
    const target = workspaces.find((w) => w.slug === slug);
    if (!target) {
      const fallback = workspace ?? workspaces[0]!;
      void router.replace(`/${fallback.slug}`);
      return;
    }
    if (workspace?.id !== target.id) {
      setWorkspaceId(target.id);
    }
  }, [slug, workspaces, workspace, isLoading, router, setWorkspaceId]);

  if (isLoading || !workspace) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar workspaceSlug={workspace.slug} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  );
}
