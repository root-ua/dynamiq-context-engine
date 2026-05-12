"use client";
import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

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
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ontologyApi } from "@/lib/api/endpoints";
import type { EntityType } from "@/lib/api/types";
import { SchemaEditor } from "./SchemaEditor";

interface TypeCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  allTypes: EntityType[];
  workspaceId: string;
  onCreated?: (type: EntityType) => void;
}

const DEFAULT_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {},
};

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function TypeCreateDialog({
  open,
  onOpenChange,
  allTypes,
  workspaceId,
  onCreated,
}: TypeCreateDialogProps) {
  const { push } = useToast();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [slugDirty, setSlugDirty] = React.useState(false);
  const [extendsSlug, setExtendsSlug] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [icon, setIcon] = React.useState("");
  const [color, setColor] = React.useState("");
  const [schema, setSchema] =
    React.useState<Record<string, unknown>>(DEFAULT_SCHEMA);

  React.useEffect(() => {
    if (!open) {
      setName("");
      setSlug("");
      setSlugDirty(false);
      setExtendsSlug("");
      setDescription("");
      setIcon("");
      setColor("");
      setSchema(DEFAULT_SCHEMA);
    }
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () =>
      ontologyApi.createType(workspaceId, {
        name,
        slug: slug || slugify(name),
        extends: extendsSlug || null,
        description: description || null,
        ui_hints: { icon: icon || undefined, color: color || undefined },
        schema,
      }),
    onSuccess: (created) => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "types"],
      });
      push({ title: "Type created", description: `${created.name} added.` });
      onOpenChange(false);
      onCreated?.(created);
    },
    onError: (e: Error) =>
      push({
        title: "Create failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New entity type</DialogTitle>
          <DialogDescription>
            Define a new type of entity for this workspace. System types are
            built in; yours extend or sit alongside them.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="new-type-name">Name</Label>
              <Input
                id="new-type-name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slugDirty) setSlug(slugify(e.target.value));
                }}
                placeholder="Customer"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-type-slug">Slug</Label>
              <Input
                id="new-type-slug"
                value={slug}
                onChange={(e) => {
                  setSlug(slugify(e.target.value));
                  setSlugDirty(true);
                }}
                placeholder="customer"
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="new-type-extends">Extends</Label>
            <Select
              id="new-type-extends"
              value={extendsSlug}
              onChange={(e) => setExtendsSlug(e.target.value)}
            >
              <option value="">(no parent)</option>
              {allTypes.map((t) => (
                <option key={t.id} value={t.slug}>
                  {t.name} ({t.hierarchy})
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="new-type-desc">Description</Label>
            <Textarea
              id="new-type-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A paying account that belongs to a company."
            />
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="new-type-icon">Icon</Label>
              <Input
                id="new-type-icon"
                placeholder="user"
                value={icon}
                onChange={(e) => setIcon(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-type-color">Color</Label>
              <Input
                id="new-type-color"
                placeholder="#10b981"
                value={color}
                onChange={(e) => setColor(e.target.value)}
              />
            </div>
          </div>

          <div>
            <Label className="mb-2 block">Schema</Label>
            <SchemaEditor value={schema} onChange={setSchema} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={!name.trim() || createMutation.isPending}
          >
            Create type
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
