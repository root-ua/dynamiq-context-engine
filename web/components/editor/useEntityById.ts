"use client";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { entitiesApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";
import type { Entity } from "@/lib/api/types";

export function entityQueryKey(workspaceId: string | null, entityId: string) {
  return ["entity", workspaceId ?? "none", entityId] as const;
}

/**
 * Fetch a single entity by id, cached by (workspace, id). Safe to call
 * many times — BlockNote may render dozens of mentions on a page.
 */
export function useEntityById(
  entityId: string | null | undefined,
): UseQueryResult<Entity> {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
  return useQuery({
    queryKey: entityQueryKey(workspaceId, entityId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("no workspace selected");
      if (!entityId) throw new Error("no entity id");
      return entitiesApi.get(workspaceId, entityId);
    },
    enabled: !!workspaceId && !!entityId,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });
}
