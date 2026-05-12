"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { PiSparkle as Sparkles } from "react-icons/pi";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { entitiesApi } from "@/lib/api/endpoints";

import { toSeedEntity, type SeedEntity } from "./types";

/** Full-page skeleton shown while traversal is in flight. */
export function SkeletonCanvas() {
  return (
    <div className="relative flex-1 overflow-hidden">
      <div className="absolute inset-0 animate-pulse bg-[radial-gradient(circle_at_50%_40%,rgba(99,102,241,0.12),transparent_60%)]" />
      {Array.from({ length: 14 }, (_, i) => {
        const x = 12 + ((i * 53) % 76);
        const y = 18 + ((i * 31) % 60);
        const size = 12 + (i % 5) * 4;
        return (
          <div
            key={i}
            className="absolute animate-pulse rounded-full bg-muted"
            style={{
              left: `${x}%`,
              top: `${y}%`,
              width: size,
              height: size,
              animationDelay: `${i * 80}ms`,
            }}
          />
        );
      })}
      <div className="pointer-events-none absolute inset-x-0 bottom-10 text-center text-xs text-muted-foreground">
        Traversing graph…
      </div>
    </div>
  );
}

/** Floating node/edge count pill, top-right of the graph canvas. */
export function StatsBar({
  nodeCount,
  edgeCount,
  truncated,
  cap,
}: {
  nodeCount: number;
  edgeCount: number;
  truncated: boolean;
  cap: number;
}) {
  return (
    <div className="pointer-events-none absolute right-4 top-4 flex items-center gap-2 rounded-md border bg-background/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
      <span>{nodeCount} nodes</span>
      <span className="text-border">|</span>
      <span>{edgeCount} edges</span>
      {truncated && (
        <span className="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-700 dark:text-amber-300">
          capped at {cap}
        </span>
      )}
    </div>
  );
}

/**
 * No-seeds empty state: big hero card with entity suggestions. The user's
 * first interaction starts the graph.
 */
export function EmptyGraphState({
  workspaceId,
  onAddSeed,
}: {
  workspaceId: string;
  onAddSeed: (s: SeedEntity) => void;
}) {
  const suggestions = useQuery({
    queryKey: ["graph.suggestions", workspaceId],
    queryFn: () => entitiesApi.list(workspaceId, { limit: 5 }),
    enabled: !!workspaceId,
  });

  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <Card className="w-full max-w-xl">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
            <Sparkles className="h-5 w-5 text-primary" />
          </div>
          <CardTitle>Pick an entity to start exploring</CardTitle>
          <CardDescription>
            Search above to seed the graph, or jump into one of these entities
            from your workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            {suggestions.isLoading && (
              <div className="h-9 animate-pulse rounded-md bg-muted" />
            )}
            {suggestions.data?.length === 0 && (
              <div className="py-6 text-center text-sm text-muted-foreground">
                No entities yet. Ingest some content first.
              </div>
            )}
            {suggestions.data?.map((e) => (
              <button
                key={e.id}
                type="button"
                onClick={() => onAddSeed(toSeedEntity(e))}
                className="group flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
              >
                <Sparkles className="h-3.5 w-3.5 text-muted-foreground transition-colors group-hover:text-primary" />
                <span className="min-w-0 flex-1 truncate">{e.canonical}</span>
                {e.type_slug && (
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {e.type_slug}
                  </span>
                )}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
