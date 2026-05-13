"use client";
import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { invalidateTokenCache } from "@/lib/api/client";
import { workspacesApi } from "@/lib/api/endpoints";
import { useSession } from "@/lib/auth-client";
import type { Workspace } from "@/lib/api/types";

interface WorkspaceContextType {
  workspace: Workspace | null;
  workspaces: Workspace[];
  setWorkspaceId: (id: string) => void;
  /** Refresh the workspaces list. Returns a promise that resolves
   * after the refetch settles so callers can `await` before routing
   * into a newly-created workspace. */
  refresh: () => Promise<unknown>;
  isLoading: boolean;
}

const Ctx = React.createContext<WorkspaceContextType | null>(null);
const STORAGE_KEY = "memory:selected-workspace";

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const [selectedId, setSelectedIdState] = React.useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(STORAGE_KEY);
  });

  const { data, refetch, isLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: workspacesApi.list,
    enabled: !!session?.user,
  });

  const workspaces = React.useMemo(() => data ?? [], [data]);
  const workspace = React.useMemo(() => {
    if (!workspaces.length) return null;
    return workspaces.find((w) => w.id === selectedId) ?? workspaces[0] ?? null;
  }, [workspaces, selectedId]);

  const setWorkspaceId = React.useCallback(
    (id: string) => {
      const previousId = selectedId;
      setSelectedIdState(id);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, id);
      }
      if (previousId && previousId !== id) {
        // The new workspace has its own tenancy-scoped data; if we keep
        // the previous workspace's cached queries, the user briefly sees
        // the wrong entities while the new ones fetch. We also bust the
        // minted-JWT cache so the next request lands with the new
        // workspace in the claim.
        //
        // But we only invalidate *workspace-scoped* queries. Things like
        // the list of workspaces, the session, and the `/api/me` query
        // are workspace-neutral; nuking them causes a refetch storm that
        // made rapid switching feel slow.
        invalidateTokenCache();
        void qc.invalidateQueries({
          predicate: (q) => {
            const key = q.queryKey;
            if (!Array.isArray(key)) return false;
            // Every workspace-scoped query keys the wsId somewhere in
            // its tuple (usually index 1). If the previous id appears
            // anywhere in the key, it's per-workspace and should refresh.
            return key.some((part) => part === previousId);
          },
        });
      }
    },
    [qc, selectedId],
  );

  const value = React.useMemo<WorkspaceContextType>(
    () => ({
      workspace: workspace ?? null,
      workspaces,
      setWorkspaceId,
      refresh: () => refetch(),
      isLoading,
    }),
    [workspace, workspaces, setWorkspaceId, refetch, isLoading],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace() {
  const ctx = React.useContext(Ctx);
  if (!ctx)
    throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
