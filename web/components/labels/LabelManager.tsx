"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PiPlus as Plus, PiTrash as Trash } from "react-icons/pi";

import { LabelBadge } from "@/components/labels/LabelBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label as FormLabel } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { labelsApi } from "@/lib/api/endpoints";
import type { Label } from "@/lib/api/types";

interface Props {
  workspaceId: string;
}

const DEFAULT_COLORS = [
  "#ef4444",
  "#f97316",
  "#eab308",
  "#22c55e",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#737373",
];

export function LabelManager({ workspaceId }: Props) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [createOpen, setCreateOpen] = React.useState(false);

  const labelsQuery = useQuery({
    queryKey: ["labels", workspaceId],
    queryFn: () => labelsApi.list(workspaceId),
    enabled: !!workspaceId,
  });

  const remove = useMutation({
    mutationFn: (slug: string) => labelsApi.delete(workspaceId, slug),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labels", workspaceId] });
      push({ title: "Label removed" });
    },
    onError: (err) =>
      push({
        title: "Failed to remove",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const labels = labelsQuery.data ?? [];

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Sensitivity labels</h2>
          <p className="text-sm text-muted-foreground">
            Tag episodes and edges with labels. Policies decide what queries can
            see.
          </p>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="h-3.5 w-3.5" /> New label
        </Button>
      </div>

      {labels.length === 0 ? (
        <EmptyState
          title="No labels yet"
          description="Create your first label to start tagging facts. Use the Policies tab to define what should happen when labels combine."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {labels.map((l) => (
            <LabelRow
              key={l.id}
              label={l}
              onDelete={() => remove.mutate(l.slug)}
              busy={remove.isPending}
            />
          ))}
        </div>
      )}

      <CreateLabelDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        workspaceId={workspaceId}
        existingLabels={labels}
      />
    </>
  );
}

function LabelRow({
  label,
  onDelete,
  busy,
}: {
  label: Label;
  onDelete: () => void;
  busy: boolean;
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <LabelBadge label={label} />
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={onDelete}
            aria-label="Delete label"
          >
            <Trash className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="space-y-1 text-xs text-muted-foreground">
          <div className="font-mono">{label.path}</div>
          {label.description && (
            <p className="text-foreground/80">{label.description}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function CreateLabelDialog({
  open,
  onOpenChange,
  workspaceId,
  existingLabels,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceId: string;
  existingLabels: Label[];
}) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [slug, setSlug] = React.useState("");
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [color, setColor] = React.useState(DEFAULT_COLORS[0]);
  const [parentSlug, setParentSlug] = React.useState<string>("");

  React.useEffect(() => {
    if (!open) {
      setSlug("");
      setName("");
      setDescription("");
      setColor(DEFAULT_COLORS[0]);
      setParentSlug("");
    }
  }, [open]);

  const create = useMutation({
    mutationFn: () =>
      labelsApi.create(workspaceId, {
        slug,
        name,
        description: description || null,
        color,
        parent_slug: parentSlug || null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labels", workspaceId] });
      push({ title: "Label created" });
      onOpenChange(false);
    },
    onError: (err) =>
      push({
        title: "Create failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const canSubmit =
    slug.trim().length > 0 &&
    name.trim().length > 0 &&
    /^[a-z][a-z0-9_-]*$/.test(slug);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New label</DialogTitle>
          <DialogDescription>
            Labels can be hierarchical: e.g. <code>confidential.finance</code>.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-2">
            <FormLabel htmlFor="label-name">Name</FormLabel>
            <Input
              id="label-name"
              placeholder="Confidential"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (!slug) {
                  setSlug(
                    e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9_]+/g, "-")
                      .replace(/^-+|-+$/g, ""),
                  );
                }
              }}
            />
          </div>
          <div className="grid gap-2">
            <FormLabel htmlFor="label-slug">Slug</FormLabel>
            <Input
              id="label-slug"
              placeholder="confidential"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, digits, dashes/underscores; must start with a
              letter.
            </p>
          </div>
          <div className="grid gap-2">
            <FormLabel htmlFor="label-parent">Parent (optional)</FormLabel>
            <select
              id="label-parent"
              value={parentSlug}
              onChange={(e) => setParentSlug(e.target.value)}
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">— top-level —</option>
              {existingLabels.map((l) => (
                <option key={l.id} value={l.slug}>
                  {l.path}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2">
            <FormLabel>Color</FormLabel>
            <div className="flex flex-wrap gap-2">
              {DEFAULT_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  aria-label={`Color ${c}`}
                  className={`h-7 w-7 rounded-full border-2 transition ${
                    color === c ? "ring-2 ring-offset-2" : ""
                  }`}
                  style={{
                    backgroundColor: `${c}33`,
                    borderColor: c,
                  }}
                />
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <FormLabel htmlFor="label-desc">Description</FormLabel>
            <Textarea
              id="label-desc"
              rows={2}
              placeholder="What this label means"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!canSubmit || create.isPending}
            onClick={() => create.mutate()}
          >
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
