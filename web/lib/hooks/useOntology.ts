import { useQuery } from "@tanstack/react-query";

import { ontologyApi } from "@/lib/api/endpoints";

/**
 * Cached ontology snapshot for the workspace.
 *
 * The ontology is "almost-static" — changes rarely in normal usage, so
 * a 5-minute stale-time keeps the graph filters, entity type pickers,
 * and form builders from re-fetching on every mount. Mutations that
 * change the ontology should call `queryClient.invalidateQueries({ queryKey: ["ontology"] })`.
 */
export function useOntology(workspaceId: string) {
  const types = useQuery({
    queryKey: ["ontology", workspaceId, "types"],
    queryFn: () => ontologyApi.listTypes(workspaceId),
    enabled: !!workspaceId,
    staleTime: 5 * 60 * 1000,
  });
  const relations = useQuery({
    queryKey: ["ontology", workspaceId, "relations"],
    queryFn: () => ontologyApi.listRelations(workspaceId),
    enabled: !!workspaceId,
    staleTime: 5 * 60 * 1000,
  });
  return { types, relations };
}
