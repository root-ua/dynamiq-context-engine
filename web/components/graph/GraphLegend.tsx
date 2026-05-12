"use client";

import * as React from "react";

import type { GraphPayload } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { colorForType } from "./types";

export interface GraphLegendProps {
  payload: GraphPayload | undefined;
  className?: string;
}

/**
 * Small floating legend that lists the node-color mapping for the types
 * actually present in the current view, along with edge predicates.
 */
export function GraphLegend({ payload, className }: GraphLegendProps) {
  const { types, predicates, hidden } = React.useMemo(() => {
    if (!payload) return { types: [], predicates: [], hidden: 0 };
    const typeCounts = new Map<string, number>();
    payload.nodes.forEach((n) => {
      const t = n.type || "unknown";
      typeCounts.set(t, (typeCounts.get(t) ?? 0) + 1);
    });
    const predCounts = new Map<string, number>();
    payload.edges.forEach((e) => {
      predCounts.set(e.predicate, (predCounts.get(e.predicate) ?? 0) + 1);
    });
    const sortedTypes = [...typeCounts.entries()].sort((a, b) => b[1] - a[1]);
    const sortedPreds = [...predCounts.entries()].sort((a, b) => b[1] - a[1]);
    const MAX = 6;
    return {
      types: sortedTypes.slice(0, MAX),
      predicates: sortedPreds.slice(0, MAX),
      hidden:
        Math.max(0, sortedTypes.length - MAX) +
        Math.max(0, sortedPreds.length - MAX),
    };
  }, [payload]);

  if (!payload || (types.length === 0 && predicates.length === 0)) return null;

  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-4 left-4 z-10 w-56 rounded-lg border bg-background/90 p-3 text-xs shadow-md backdrop-blur",
        className,
      )}
    >
      {types.length > 0 && (
        <section>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Types
          </div>
          <ul className="space-y-1">
            {types.map(([type, count]) => (
              <li key={type} className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: colorForType(type) }}
                />
                <span className="min-w-0 flex-1 truncate">{type}</span>
                <span className="text-muted-foreground">{count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {predicates.length > 0 && (
        <section className="mt-3">
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Predicates
          </div>
          <ul className="space-y-1">
            {predicates.map(([pred, count]) => (
              <li key={pred} className="flex items-center gap-2">
                <svg
                  width="20"
                  height="6"
                  viewBox="0 0 20 6"
                  className="shrink-0"
                >
                  <line
                    x1="0"
                    y1="3"
                    x2="16"
                    y2="3"
                    stroke="rgb(100,116,139)"
                    strokeWidth="1.5"
                  />
                  <polygon points="16,0 20,3 16,6" fill="rgb(100,116,139)" />
                </svg>
                <span className="min-w-0 flex-1 truncate font-mono">
                  {pred}
                </span>
                <span className="text-muted-foreground">{count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {hidden > 0 && (
        <div className="mt-2 text-[10px] text-muted-foreground">
          +{hidden} more
        </div>
      )}
    </div>
  );
}
