"use client";
import * as React from "react";
import { PiMagnifyingGlass as Search } from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { EntityType, RelationType } from "@/lib/api/types";

interface RelationListProps {
  relations: RelationType[];
  types: EntityType[];
  selectedSlug?: string | null;
  onSelect: (relation: RelationType) => void;
}

export function RelationList({
  relations,
  types,
  selectedSlug,
  onSelect,
}: RelationListProps) {
  const [query, setQuery] = React.useState("");
  const typeById = React.useMemo(() => {
    const m = new Map<string, EntityType>();
    types.forEach((t) => m.set(t.id, t));
    return m;
  }, [types]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return relations;
    return relations.filter((r) => {
      const domain = r.domain_type_id ? typeById.get(r.domain_type_id) : null;
      const range = r.range_type_id ? typeById.get(r.range_type_id) : null;
      return (
        r.slug.toLowerCase().includes(q) ||
        r.name.toLowerCase().includes(q) ||
        (r.description ?? "").toLowerCase().includes(q) ||
        domain?.slug.toLowerCase().includes(q) ||
        range?.slug.toLowerCase().includes(q)
      );
    });
  }, [relations, query, typeById]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter relations..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 ? (
          <div className="py-10 text-center text-xs text-muted-foreground">
            No relations match.
          </div>
        ) : (
          <ul className="space-y-1">
            {filtered.map((r) => {
              const domain = r.domain_type_id
                ? typeById.get(r.domain_type_id)
                : null;
              const range = r.range_type_id
                ? typeById.get(r.range_type_id)
                : null;
              const isSelected = r.slug === selectedSlug;
              return (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(r)}
                    className={cn(
                      "flex w-full flex-col gap-1 rounded-md border px-3 py-2 text-left text-sm transition-colors",
                      isSelected
                        ? "border-primary bg-accent"
                        : "border-transparent hover:bg-muted",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{r.name}</span>
                      {r.system && <Badge variant="outline">system</Badge>}
                    </div>
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {r.slug}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      <span className="font-mono">
                        {domain ? domain.slug : "any"}
                      </span>
                      <span className="mx-1">→</span>
                      <span className="font-mono">
                        {range ? range.slug : "any"}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1 pt-1">
                      {r.symmetric && <Chip>symmetric</Chip>}
                      {r.transitive && <Chip>transitive</Chip>}
                      {r.temporal && <Chip>temporal</Chip>}
                      {r.high_stakes && <Chip tone="warn">high-stakes</Chip>}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function Chip({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "warn";
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full border px-2 text-[10px] font-medium",
        tone === "warn"
          ? "border-amber-400/50 bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          : "bg-muted text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}
