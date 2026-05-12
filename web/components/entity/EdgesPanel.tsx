"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PiArrowRight as ArrowRight, PiTrash as Trash } from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { edgesApi, entitiesApi } from "@/lib/api/endpoints";
import type { Edge } from "@/lib/api/types";

export function EdgesPanel({
  workspaceId,
  workspaceSlug,
  entityId,
  entityName,
}: {
  workspaceId: string;
  workspaceSlug: string;
  entityId: string;
  entityName: string;
}) {
  const qc = useQueryClient();
  const { push } = useToast();

  const outQuery = useQuery({
    queryKey: ["entity-edges", workspaceId, entityId, "out"],
    queryFn: () =>
      entitiesApi.edges(workspaceId, entityId, { direction: "out" }),
  });
  const inQuery = useQuery({
    queryKey: ["entity-edges", workspaceId, entityId, "in"],
    queryFn: () =>
      entitiesApi.edges(workspaceId, entityId, { direction: "in" }),
  });

  async function invalidate(edge: Edge) {
    try {
      await edgesApi.invalidate(workspaceId, edge.id, "closed from UI");
      push({ title: "Edge closed" });
      void qc.invalidateQueries({
        queryKey: ["entity-edges", workspaceId, entityId],
      });
    } catch (err: unknown) {
      push({
        title: "Failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Column
        title={`${entityName} → …`}
        edges={outQuery.data ?? []}
        renderTarget={(e) => (
          <Link
            className="underline underline-offset-2"
            href={`/${workspaceSlug}/entities/${e.object_id}`}
          >
            {e.fact.split(` ${e.predicate_slug} `).slice(-1)[0] ?? e.object_id}
          </Link>
        )}
        onInvalidate={invalidate}
      />
      <Column
        title={`… → ${entityName}`}
        edges={inQuery.data ?? []}
        renderTarget={(e) => (
          <Link
            className="underline underline-offset-2"
            href={`/${workspaceSlug}/entities/${e.subject_id}`}
          >
            {e.fact.split(` ${e.predicate_slug} `)[0] ?? e.subject_id}
          </Link>
        )}
        onInvalidate={invalidate}
      />
    </div>
  );
}

function Column({
  title,
  edges,
  renderTarget,
  onInvalidate,
}: {
  title: string;
  edges: Edge[];
  renderTarget: (e: Edge) => React.ReactNode;
  onInvalidate: (e: Edge) => void;
}) {
  return (
    <div className="rounded-md border">
      <div className="border-b px-3 py-2 text-xs font-medium uppercase text-muted-foreground">
        {title}
      </div>
      {edges.length === 0 ? (
        <div className="p-4 text-sm text-muted-foreground">No edges.</div>
      ) : (
        <ul className="divide-y">
          {edges.map((e) => (
            <li
              key={e.id}
              className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <div className="flex min-w-0 items-center gap-2">
                <Badge variant="secondary">{e.predicate_slug}</Badge>
                <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                <div className="truncate">{renderTarget(e)}</div>
              </div>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => onInvalidate(e)}
                title="Close edge"
              >
                <Trash className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
