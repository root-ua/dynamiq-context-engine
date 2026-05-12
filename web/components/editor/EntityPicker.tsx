"use client";
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  PiSpinnerGap as Loader2,
  PiPlus as Plus,
  PiMagnifyingGlass as Search,
} from "react-icons/pi";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { entitiesApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";
import type { Entity } from "@/lib/api/types";
import { EntityCreateDialog } from "@/components/editor/EntityCreateDialog";

interface EntityPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialQuery?: string;
  /** Fired when the user picks or creates an entity. */
  onPick: (entity: Entity, typeSlug: string) => void;
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}

export function EntityPicker({
  open,
  onOpenChange,
  initialQuery,
  onPick,
}: EntityPickerProps) {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;

  const [query, setQuery] = React.useState(initialQuery ?? "");
  const [activeIndex, setActiveIndex] = React.useState(0);
  const [createOpen, setCreateOpen] = React.useState(false);
  const debouncedQuery = useDebounced(query.trim(), 200);

  React.useEffect(() => {
    if (open) {
      setQuery(initialQuery ?? "");
      setActiveIndex(0);
    }
  }, [open, initialQuery]);

  const listQuery = useQuery({
    queryKey: ["entities", workspaceId, debouncedQuery],
    queryFn: () => {
      if (!workspaceId) throw new Error("no workspace");
      return entitiesApi.list(workspaceId, {
        query: debouncedQuery || undefined,
        limit: 20,
      });
    },
    enabled: !!workspaceId && open,
    staleTime: 10_000,
  });

  const results = listQuery.data ?? [];

  React.useEffect(() => {
    setActiveIndex((idx) =>
      results.length === 0 ? 0 : Math.min(idx, results.length - 1),
    );
  }, [results.length]);

  const pick = (entity: Entity) => {
    onPick(entity, entity.type_slug ?? "");
    onOpenChange(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((idx) =>
        Math.min(idx + 1, Math.max(results.length - 1, 0)),
      );
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((idx) => Math.max(idx - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = results[activeIndex];
      if (target) pick(target);
      else if (query.trim().length > 0) setCreateOpen(true);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0">
          <DialogHeader className="px-4 pt-4">
            <DialogTitle>Insert entity</DialogTitle>
            <DialogDescription>
              Pick an entity to mention, or create a new one.
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-2 border-b px-4 py-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <Input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Search by name or alias…"
              className="h-8 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
            />
            {listQuery.isFetching && (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>

          <ul
            role="listbox"
            className="max-h-72 overflow-y-auto py-1"
            aria-label="entity matches"
          >
            {results.length === 0 && !listQuery.isLoading && (
              <li className="px-4 py-6 text-center text-sm text-muted-foreground">
                {query.trim()
                  ? "No matches. Try “Create new” below."
                  : "Start typing to search…"}
              </li>
            )}
            {results.map((entity, index) => {
              const active = index === activeIndex;
              const aliases = entity.aliases?.slice(0, 3) ?? [];
              return (
                <li key={entity.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => pick(entity)}
                    className={cn(
                      "flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm transition-colors",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "hover:bg-accent/50",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">
                        {entity.canonical}
                      </div>
                      {aliases.length > 0 && (
                        <div className="truncate text-xs text-muted-foreground">
                          aka {aliases.join(", ")}
                        </div>
                      )}
                    </div>
                    {entity.type_slug && (
                      <Badge variant="secondary" className="shrink-0">
                        {entity.type_slug}
                      </Badge>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="flex items-center justify-between gap-2 border-t px-4 py-2">
            <div className="text-xs text-muted-foreground">
              <span className="rounded border px-1">↑↓</span> navigate{" "}
              <span className="rounded border px-1">↵</span> insert
            </div>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setCreateOpen(true)}
            >
              <Plus className="h-4 w-4" /> Create new
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <EntityCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        initialCanonical={query.trim()}
        onCreated={(entity, typeSlug) => {
          onPick(entity, typeSlug);
          onOpenChange(false);
        }}
      />
    </>
  );
}
