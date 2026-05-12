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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ontologyApi } from "@/lib/api/endpoints";
import type { EntityType, RelationType } from "@/lib/api/types";

interface RelationCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  types: EntityType[];
  relations: RelationType[];
  workspaceId: string;
  onCreated?: (relation: RelationType) => void;
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function RelationCreateDialog({
  open,
  onOpenChange,
  types,
  relations,
  workspaceId,
  onCreated,
}: RelationCreateDialogProps) {
  const { push } = useToast();
  const qc = useQueryClient();

  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [slugDirty, setSlugDirty] = React.useState(false);
  const [description, setDescription] = React.useState("");
  const [domainSlug, setDomainSlug] = React.useState("");
  const [rangeSlug, setRangeSlug] = React.useState("");
  const [cardSubj, setCardSubj] = React.useState<"one" | "many">("many");
  const [cardObj, setCardObj] = React.useState<"one" | "many">("many");
  const [inverseSlug, setInverseSlug] = React.useState("");
  const [symmetric, setSymmetric] = React.useState(false);
  const [transitive, setTransitive] = React.useState(false);
  const [temporal, setTemporal] = React.useState(false);
  const [highStakes, setHighStakes] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setName("");
      setSlug("");
      setSlugDirty(false);
      setDescription("");
      setDomainSlug("");
      setRangeSlug("");
      setCardSubj("many");
      setCardObj("many");
      setInverseSlug("");
      setSymmetric(false);
      setTransitive(false);
      setTemporal(false);
      setHighStakes(false);
    }
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () =>
      ontologyApi.createRelation(workspaceId, {
        name,
        slug: slug || slugify(name),
        description: description || null,
        domain: domainSlug || undefined,
        range: rangeSlug || undefined,
        cardinality_subject: cardSubj,
        cardinality_object: cardObj,
        inverse_of: inverseSlug || null,
        symmetric,
        transitive,
        temporal,
        high_stakes: highStakes,
      }),
    onSuccess: (created) => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "relations"],
      });
      push({
        title: "Relation created",
        description: `${created.name} added.`,
      });
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
          <DialogTitle>New relation</DialogTitle>
          <DialogDescription>
            Define how two entity types relate. You can mark relations as
            symmetric, transitive, or temporal.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="new-rel-name">Name</Label>
              <Input
                id="new-rel-name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slugDirty) setSlug(slugify(e.target.value));
                }}
                placeholder="works at"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-rel-slug">Slug</Label>
              <Input
                id="new-rel-slug"
                value={slug}
                onChange={(e) => {
                  setSlug(slugify(e.target.value));
                  setSlugDirty(true);
                }}
                placeholder="works_at"
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="new-rel-desc">Description</Label>
            <Textarea
              id="new-rel-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A person's current employer."
            />
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="new-rel-domain">Domain</Label>
              <Select
                id="new-rel-domain"
                value={domainSlug}
                onChange={(e) => setDomainSlug(e.target.value)}
              >
                <option value="">(any)</option>
                {types.map((t) => (
                  <option key={t.id} value={t.slug}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-rel-range">Range</Label>
              <Select
                id="new-rel-range"
                value={rangeSlug}
                onChange={(e) => setRangeSlug(e.target.value)}
              >
                <option value="">(any)</option>
                {types.map((t) => (
                  <option key={t.id} value={t.slug}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="new-rel-cs">Cardinality (subject)</Label>
              <Select
                id="new-rel-cs"
                value={cardSubj}
                onChange={(e) => setCardSubj(e.target.value as "one" | "many")}
              >
                <option value="one">one</option>
                <option value="many">many</option>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-rel-co">Cardinality (object)</Label>
              <Select
                id="new-rel-co"
                value={cardObj}
                onChange={(e) => setCardObj(e.target.value as "one" | "many")}
              >
                <option value="one">one</option>
                <option value="many">many</option>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="new-rel-inverse">Inverse of</Label>
            <Select
              id="new-rel-inverse"
              value={inverseSlug}
              onChange={(e) => setInverseSlug(e.target.value)}
            >
              <option value="">(none)</option>
              {relations.map((r) => (
                <option key={r.id} value={r.slug}>
                  {r.name}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid gap-3 rounded-lg border p-4 md:grid-cols-2">
            <ToggleRow
              label="Symmetric"
              checked={symmetric}
              onChange={setSymmetric}
              description="A↔B is equivalent."
            />
            <ToggleRow
              label="Transitive"
              checked={transitive}
              onChange={setTransitive}
              description="A→B→C implies A→C."
            />
            <ToggleRow
              label="Temporal"
              checked={temporal}
              onChange={setTemporal}
              description="Tracks valid-from/valid-to."
            />
            <ToggleRow
              label="High stakes"
              checked={highStakes}
              onChange={setHighStakes}
              description="Requires confirmation."
            />
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
            Create relation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3">
      <Switch checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <div className="space-y-0.5">
        <div className="text-sm font-medium">{label}</div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </label>
  );
}
