"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LabelBadge } from "@/components/labels/LabelBadge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { labelsApi } from "@/lib/api/endpoints";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceId: string;
  target: { kind: "edge" | "episode"; id: string } | null;
  /** Slugs already assigned (so we can hide them). */
  alreadyAssigned?: string[];
  onAssigned?: (slug: string) => void;
}

export function AssignLabelDialog({
  open,
  onOpenChange,
  workspaceId,
  target,
  alreadyAssigned = [],
  onAssigned,
}: Props) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const labelsQuery = useQuery({
    queryKey: ["labels", workspaceId],
    queryFn: () => labelsApi.list(workspaceId),
    enabled: !!workspaceId && open,
  });

  const assign = useMutation({
    mutationFn: (slug: string) => {
      if (!target) throw new Error("no target");
      return labelsApi.assign(workspaceId, slug, {
        target_kind: target.kind,
        target_id: target.id,
      });
    },
    onSuccess: (_data, slug) => {
      push({ title: `Label "${slug}" assigned` });
      onAssigned?.(slug);
      void qc.invalidateQueries({
        queryKey: ["labels-for", target?.kind, target?.id],
      });
      onOpenChange(false);
    },
    onError: (err) =>
      push({
        title: "Failed to assign",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const candidates = (labelsQuery.data ?? [])
    .filter((l) => !alreadyAssigned.includes(l.slug))
    .filter((l) =>
      query
        ? l.name.toLowerCase().includes(query.toLowerCase()) ||
          l.slug.toLowerCase().includes(query.toLowerCase())
        : true,
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Assign label</DialogTitle>
          <DialogDescription>
            Pick a label to attach to this {target?.kind ?? "item"}.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            autoFocus
            placeholder="Filter labels…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="max-h-72 overflow-y-auto rounded-md border">
            {candidates.length === 0 ? (
              <p className="p-3 text-sm text-muted-foreground">
                {labelsQuery.isLoading
                  ? "Loading labels…"
                  : "No matching labels."}
              </p>
            ) : (
              <ul className="divide-y">
                {candidates.map((l) => (
                  <li
                    key={l.id}
                    className="flex items-center justify-between gap-2 p-2"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <LabelBadge label={l} />
                      {l.description && (
                        <span className="truncate text-xs text-muted-foreground">
                          {l.description}
                        </span>
                      )}
                    </div>
                    <Button
                      size="sm"
                      disabled={assign.isPending}
                      onClick={() => assign.mutate(l.slug)}
                    >
                      Assign
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
