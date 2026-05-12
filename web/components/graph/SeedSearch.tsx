"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { PiMagnifyingGlass as Search, PiX as X } from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { entitiesApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";
import type { Entity } from "@/lib/api/types";

import { colorForType, toSeedEntity, type SeedEntity } from "./types";

export interface SeedSearchProps {
  workspaceId: string;
  seeds: SeedEntity[];
  onAdd: (seed: SeedEntity) => void;
  onRemove: (id: string) => void;
  className?: string;
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

export function SeedSearch({
  workspaceId,
  seeds,
  onAdd,
  onRemove,
  className,
}: SeedSearchProps) {
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [highlight, setHighlight] = React.useState(0);
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const debounced = useDebounced(query, 200);

  const results = useQuery({
    queryKey: ["entities.search", workspaceId, debounced],
    queryFn: () =>
      entitiesApi.list(workspaceId, {
        query: debounced || undefined,
        limit: 10,
      }),
    enabled: !!workspaceId && debounced.trim().length > 0,
  });

  React.useEffect(() => {
    setHighlight(0);
  }, [results.data]);

  // Close dropdown when clicking outside.
  React.useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  const seedIds = React.useMemo(() => new Set(seeds.map((s) => s.id)), [seeds]);
  const filtered = (results.data ?? []).filter((e) => !seedIds.has(e.id));

  const commit = React.useCallback(
    (e: Entity) => {
      onAdd(toSeedEntity(e));
      setQuery("");
      setOpen(false);
    },
    [onAdd],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((h) => Math.min(filtered.length - 1, h + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (event.key === "Enter") {
      const picked = filtered[highlight];
      if (picked) {
        event.preventDefault();
        commit(picked);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => query && setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search entities to seed…"
          className="pl-8"
          aria-expanded={open}
          aria-autocomplete="list"
          role="combobox"
        />
      </div>

      {open && debounced.trim() && (
        <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-72 overflow-y-auto rounded-md border bg-popover p-1 shadow-lg">
          {results.isLoading && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              Searching…
            </div>
          )}
          {results.isError && (
            <div className="px-3 py-2 text-xs text-destructive">
              Search failed.
            </div>
          )}
          {results.data && filtered.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              No matches.
            </div>
          )}
          {filtered.map((e, i) => (
            <button
              key={e.id}
              type="button"
              onClick={() => commit(e)}
              onMouseEnter={() => setHighlight(i)}
              className={cn(
                "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm",
                highlight === i ? "bg-accent" : "hover:bg-accent/60",
              )}
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: colorForType(e.type_slug ?? "unknown") }}
              />
              <span className="min-w-0 flex-1 truncate">{e.canonical}</span>
              {e.type_slug && (
                <Badge
                  variant="outline"
                  className="ml-auto font-mono text-[10px]"
                >
                  {e.type_slug}
                </Badge>
              )}
            </button>
          ))}
        </div>
      )}

      {seeds.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {seeds.map((s) => (
            <Badge
              key={s.id}
              variant="secondary"
              className="gap-1.5 py-1 pl-2 pr-1 text-xs font-normal"
            >
              {s.type && (
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: colorForType(s.type) }}
                />
              )}
              <span className="max-w-[180px] truncate">{s.canonical}</span>
              <button
                type="button"
                onClick={() => onRemove(s.id)}
                className="rounded p-0.5 opacity-70 hover:bg-background hover:opacity-100"
                aria-label={`Remove seed ${s.canonical}`}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
