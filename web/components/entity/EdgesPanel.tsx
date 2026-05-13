"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiArrowRight as ArrowRight,
  PiTag as TagIcon,
  PiTrash as Trash,
} from "react-icons/pi";

import { AssignLabelDialog } from "@/components/labels/AssignLabelDialog";
import { LabelBadge } from "@/components/labels/LabelBadge";
import { ProvenancePill } from "@/components/provenance/ProvenancePill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { edgesApi, entitiesApi, labelsApi } from "@/lib/api/endpoints";
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
  const [assignTarget, setAssignTarget] = React.useState<{
    kind: "edge" | "episode";
    id: string;
  } | null>(null);

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
    <>
      <div className="grid gap-4 md:grid-cols-2">
        <Column
          title={`${entityName} → …`}
          edges={outQuery.data ?? []}
          workspaceId={workspaceId}
          renderTarget={(e) => (
            <Link
              className="underline underline-offset-2"
              href={`/${workspaceSlug}/entities/${e.object_id}`}
            >
              {e.fact.split(` ${e.predicate_slug} `).slice(-1)[0] ??
                e.object_id}
            </Link>
          )}
          onInvalidate={invalidate}
          onAssignLabel={(edge) =>
            setAssignTarget({ kind: "edge", id: edge.id })
          }
        />
        <Column
          title={`… → ${entityName}`}
          edges={inQuery.data ?? []}
          workspaceId={workspaceId}
          renderTarget={(e) => (
            <Link
              className="underline underline-offset-2"
              href={`/${workspaceSlug}/entities/${e.subject_id}`}
            >
              {e.fact.split(` ${e.predicate_slug} `)[0] ?? e.subject_id}
            </Link>
          )}
          onInvalidate={invalidate}
          onAssignLabel={(edge) =>
            setAssignTarget({ kind: "edge", id: edge.id })
          }
        />
      </div>
      <AssignLabelDialog
        open={!!assignTarget}
        onOpenChange={(o) => {
          if (!o) setAssignTarget(null);
        }}
        workspaceId={workspaceId}
        target={assignTarget}
        onAssigned={() => {
          // Invalidate the per-target label fetch so the badge appears.
          if (assignTarget) {
            void qc.invalidateQueries({
              queryKey: ["edge-labels", workspaceId, assignTarget.id],
            });
          }
        }}
      />
    </>
  );
}

function Column({
  title,
  edges,
  workspaceId,
  renderTarget,
  onInvalidate,
  onAssignLabel,
}: {
  title: string;
  edges: Edge[];
  workspaceId: string;
  renderTarget: (e: Edge) => React.ReactNode;
  onInvalidate: (e: Edge) => void;
  onAssignLabel: (e: Edge) => void;
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
            <EdgeRow
              key={e.id}
              edge={e}
              workspaceId={workspaceId}
              renderTarget={renderTarget}
              onInvalidate={onInvalidate}
              onAssignLabel={onAssignLabel}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function EdgeRow({
  edge,
  workspaceId,
  renderTarget,
  onInvalidate,
  onAssignLabel,
}: {
  edge: Edge;
  workspaceId: string;
  renderTarget: (e: Edge) => React.ReactNode;
  onInvalidate: (e: Edge) => void;
  onAssignLabel: (e: Edge) => void;
}) {
  const qc = useQueryClient();
  const labelsQuery = useQuery({
    queryKey: ["edge-labels", workspaceId, edge.id],
    queryFn: () => labelsApi.forTarget(workspaceId, "edge", edge.id),
    enabled: !!workspaceId,
  });
  const labels = labelsQuery.data ?? [];

  return (
    <li className="space-y-2 px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Badge variant="secondary">{edge.predicate_slug}</Badge>
          <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          <div className="truncate">{renderTarget(edge)}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            onClick={() => onAssignLabel(edge)}
            title="Assign label"
          >
            <TagIcon className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => onInvalidate(edge)}
            title="Close edge"
          >
            <Trash className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <ProvenancePill
          workspaceId={workspaceId}
          edgeId={edge.id}
          createdAt={edge.created_at}
        />
        {edge.confidence !== null && edge.confidence !== undefined ? (
          <span
            className="rounded-full border bg-background px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
            title="Confidence"
          >
            {edge.confidence.toFixed(2)}
          </span>
        ) : null}
        <span
          className="rounded-full border bg-background px-2 py-0.5 text-[10px] text-muted-foreground"
          title={`Valid from ${edge.valid_from}`}
        >
          {freshnessLabel(edge.valid_from)}
        </span>
        {labels.map((l) => (
          <LabelBadge
            key={l.id}
            label={l}
            onRemove={async () => {
              await labelsApi.unassign(workspaceId, l.slug, {
                target_kind: "edge",
                target_id: edge.id,
              });
              void qc.invalidateQueries({
                queryKey: ["edge-labels", workspaceId, edge.id],
              });
            }}
          />
        ))}
      </div>
    </li>
  );
}

function freshnessLabel(validFrom: string): string {
  const t = Date.parse(validFrom);
  if (Number.isNaN(t)) return validFrom;
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days < 1) return "today";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}
