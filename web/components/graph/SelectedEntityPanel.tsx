"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  PiArrowRight as ArrowRight,
  PiArrowSquareOut as ExternalLink,
  PiTarget as Target,
  PiX as X,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { entitiesApi } from "@/lib/api/endpoints";
import type { GraphPayload } from "@/lib/api/types";

import { colorForType } from "./types";

export interface SelectedEntityPanelProps {
  workspaceId: string;
  workspaceSlug: string;
  nodeId: string;
  payload: GraphPayload | undefined;
  onClose: () => void;
  onFocus: (nodeId: string) => void;
}

export function SelectedEntityPanel({
  workspaceId,
  workspaceSlug,
  nodeId,
  payload,
  onClose,
  onFocus,
}: SelectedEntityPanelProps) {
  const entityQuery = useQuery({
    queryKey: ["entity", workspaceId, nodeId],
    queryFn: () => entitiesApi.get(workspaceId, nodeId),
    enabled: !!workspaceId && !!nodeId,
  });

  const edgesQuery = useQuery({
    queryKey: ["entity.edges", workspaceId, nodeId, "out"],
    queryFn: () => entitiesApi.edges(workspaceId, nodeId, { direction: "out" }),
    enabled: !!workspaceId && !!nodeId,
  });

  const objectLabelById = React.useMemo(() => {
    const m = new Map<string, string>();
    payload?.nodes.forEach((n) => m.set(n.id, n.canonical));
    return m;
  }, [payload]);

  const entity = entityQuery.data;
  const edges = (edgesQuery.data ?? []).slice(0, 5);
  const typeSlug = entity?.type_slug ?? null;

  return (
    <aside className="flex h-full w-full flex-col border-l bg-background">
      <div className="flex items-start justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {typeSlug && (
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: colorForType(typeSlug) }}
              />
            )}
            <div className="truncate text-sm font-semibold">
              {entity?.canonical ??
                (entityQuery.isLoading ? "Loading…" : "Entity")}
            </div>
          </div>
          {typeSlug && (
            <Badge variant="secondary" className="mt-1.5 font-mono text-[10px]">
              {typeSlug}
            </Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Close panel</span>
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {entity?.summary && (
          <section className="mb-4">
            <SectionTitle>Summary</SectionTitle>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {entity.summary}
            </p>
          </section>
        )}

        {entity?.aliases && entity.aliases.length > 0 && (
          <section className="mb-4">
            <SectionTitle>Aliases</SectionTitle>
            <div className="flex flex-wrap gap-1">
              {entity.aliases.map((a) => (
                <Badge key={a} variant="outline" className="text-[10px]">
                  {a}
                </Badge>
              ))}
            </div>
          </section>
        )}

        <section className="mb-4">
          <SectionTitle>Outgoing edges</SectionTitle>
          {edgesQuery.isLoading && (
            <div className="text-xs text-muted-foreground">Loading…</div>
          )}
          {edgesQuery.data && edges.length === 0 && (
            <div className="text-xs text-muted-foreground">
              No outgoing edges.
            </div>
          )}
          <ul className="space-y-1.5">
            {edges.map((e) => (
              <li
                key={e.id}
                className="flex items-start gap-2 rounded-md border px-2 py-1.5 text-xs"
              >
                <Badge
                  variant="outline"
                  className="shrink-0 font-mono text-[10px]"
                >
                  {e.predicate_slug ?? "—"}
                </Badge>
                <ArrowRight className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">
                  {objectLabelById.get(e.object_id) ?? e.object_id.slice(0, 8)}
                </span>
              </li>
            ))}
          </ul>
          {edgesQuery.data && edgesQuery.data.length > edges.length && (
            <div className="mt-1.5 text-[10px] text-muted-foreground">
              Showing 5 of {edgesQuery.data.length}.
            </div>
          )}
        </section>

        {entity?.props && Object.keys(entity.props).length > 0 && (
          <section className="mb-4">
            <SectionTitle>Properties</SectionTitle>
            <dl className="space-y-1 text-xs">
              {Object.entries(entity.props)
                .slice(0, 8)
                .map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt className="w-24 shrink-0 truncate font-mono text-muted-foreground">
                      {k}
                    </dt>
                    <dd className="flex-1 truncate">{renderPropValue(v)}</dd>
                  </div>
                ))}
            </dl>
          </section>
        )}
      </div>

      <Separator />
      <div className="flex flex-col gap-2 p-3">
        <Button
          size="sm"
          variant="default"
          onClick={() => onFocus(nodeId)}
          className="gap-2"
        >
          <Target className="h-3.5 w-3.5" />
          Focus on this
        </Button>
        <Button asChild size="sm" variant="outline" className="gap-2">
          <Link href={`/${workspaceSlug}/entities/${nodeId}`}>
            <ExternalLink className="h-3.5 w-3.5" />
            Open entity
          </Link>
        </Button>
      </div>
    </aside>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </div>
  );
}

function renderPropValue(v: unknown): string {
  if (v == null) return "—";
  if (
    typeof v === "string" ||
    typeof v === "number" ||
    typeof v === "boolean"
  ) {
    return String(v);
  }
  try {
    return JSON.stringify(v);
  } catch {
    return "[unserializable]";
  }
}
