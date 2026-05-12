"use client";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PiSpinnerGap as Loader2 } from "react-icons/pi";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { entitiesApi, ontologyApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";
import type { Entity, EntityType } from "@/lib/api/types";

interface EntityCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Optional initial values coming from the slash menu (e.g. block text). */
  initialCanonical?: string;
  initialTypeSlug?: string | null;
  onCreated: (entity: Entity, typeSlug: string) => void;
}

function isAbstractType(t: EntityType): boolean {
  const hints = t.ui_hints as { abstract?: unknown } | undefined;
  return hints?.abstract === true;
}

export function EntityCreateDialog({
  open,
  onOpenChange,
  initialCanonical,
  initialTypeSlug,
  onCreated,
}: EntityCreateDialogProps) {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
  const toast = useToast();
  const queryClient = useQueryClient();

  const typesQuery = useQuery({
    queryKey: ["ontology", workspaceId, "types"],
    queryFn: () => {
      if (!workspaceId) throw new Error("no workspace");
      return ontologyApi.listTypes(workspaceId);
    },
    enabled: !!workspaceId && open,
    staleTime: 60_000,
  });

  const concreteTypes = React.useMemo(() => {
    return (typesQuery.data ?? []).filter((t) => !isAbstractType(t));
  }, [typesQuery.data]);

  const [typeSlug, setTypeSlug] = React.useState<string>("");
  const [canonical, setCanonical] = React.useState<string>("");

  // Seed fields whenever the dialog opens.
  React.useEffect(() => {
    if (!open) return;
    setCanonical(initialCanonical ?? "");
    if (initialTypeSlug) {
      setTypeSlug(initialTypeSlug);
    } else if (concreteTypes.length > 0) {
      setTypeSlug((current) => current || concreteTypes[0]!.slug);
    }
  }, [open, initialCanonical, initialTypeSlug, concreteTypes]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId) throw new Error("no workspace");
      if (!typeSlug) throw new Error("pick a type");
      if (!canonical.trim()) throw new Error("canonical name required");
      return entitiesApi.create(workspaceId, {
        type: typeSlug,
        canonical: canonical.trim(),
      });
    },
    onSuccess: (entity) => {
      void queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.setQueryData(
        ["entity", workspaceId ?? "none", entity.id],
        entity,
      );
      onCreated(entity, typeSlug);
      onOpenChange(false);
    },
    onError: (err: unknown) => {
      toast.push({
        title: "Couldn't create entity",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      });
    },
  });

  const disabled = mutation.isPending || !typeSlug || !canonical.trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New entity</DialogTitle>
          <DialogDescription>
            Create a typed entity and insert it into the document.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!disabled) mutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="entity-type">Type</Label>
            <Select
              id="entity-type"
              value={typeSlug}
              onChange={(event) => setTypeSlug(event.target.value)}
              disabled={typesQuery.isLoading || concreteTypes.length === 0}
            >
              {concreteTypes.length === 0 ? (
                <option value="">Loading types…</option>
              ) : (
                concreteTypes.map((t) => (
                  <option key={t.id} value={t.slug}>
                    {t.name}
                  </option>
                ))
              )}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="entity-canonical">Canonical name</Label>
            <Input
              id="entity-canonical"
              value={canonical}
              autoFocus
              onChange={(event) => setCanonical(event.target.value)}
              placeholder="e.g. Acme Corp"
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={disabled}>
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Creating…
                </>
              ) : (
                "Create"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
