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

// Query-key prefixes that are NOT workspace-scoped. These survive a
// workspace switch without re-fetching. Everything else gets
// invalidated when the active workspace changes.
const NEUTRAL_QUERY_KEYS = new Set([
  "workspaces",
  "me",
  "session",
  "api-version",
]);

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
        // Switching workspaces means every workspace-scoped query is
        // stale. Older logic only matched queries whose key contained
        // ``previousId``; that missed queries keyed only by name
        // (e.g. ``["entities"]``), queries that had pre-fetched for
        // the new id, and queries from a third workspace cached in
        // the background. Invalidate everything except an explicit
        // workspace-neutral allowlist.
        invalidateTokenCache();
        void qc.invalidateQueries({
          predicate: (q) => {
            const key = q.queryKey;
            if (!Array.isArray(key) || key.length === 0) return false;
            const first = String(key[0]);
            return !NEUTRAL_QUERY_KEYS.has(first);
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
