"use client";
import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  PiCopy as Copy,
  PiFloppyDisk as Save,
  PiLock as Lock,
  PiTrash as Trash,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ontologyApi } from "@/lib/api/endpoints";
import type { EntityType, RelationType } from "@/lib/api/types";

interface RelationEditorProps {
  relation: RelationType;
  types: EntityType[];
  relations: RelationType[];
  workspaceId: string;
}

interface FormState {
  name: string;
  slug: string;
  description: string;
  domainSlug: string;
  rangeSlug: string;
  cardinalitySubject: "one" | "many";
  cardinalityObject: "one" | "many";
  inverseOfSlug: string;
  symmetric: boolean;
  transitive: boolean;
  temporal: boolean;
  highStakes: boolean;
}

function buildInitialForm(
  relation: RelationType,
  types: EntityType[],
  relations: RelationType[],
): FormState {
  const domain = types.find((t) => t.id === relation.domain_type_id);
  const range = types.find((t) => t.id === relation.range_type_id);
  const inverse = relations.find((r) => r.id === relation.inverse_of_id);
  return {
    name: relation.name,
    slug: relation.slug,
    description: relation.description ?? "",
    domainSlug: domain?.slug ?? "",
    rangeSlug: range?.slug ?? "",
    cardinalitySubject: relation.cardinality_subject,
    cardinalityObject: relation.cardinality_object,
    inverseOfSlug: inverse?.slug ?? "",
    symmetric: relation.symmetric,
    transitive: relation.transitive,
    temporal: relation.temporal,
    highStakes: relation.high_stakes,
  };
}

export function RelationEditor({
  relation,
  types,
  relations,
  workspaceId,
}: RelationEditorProps) {
  const { push } = useToast();
  const qc = useQueryClient();
  const [form, setForm] = React.useState<FormState>(() =>
    buildInitialForm(relation, types, relations),
  );

  React.useEffect(() => {
    setForm(buildInitialForm(relation, types, relations));
  }, [relation, types, relations]);

  const saveMutation = useMutation({
    mutationFn: () =>
      ontologyApi.updateRelation(workspaceId, relation.slug, {
        name: relation.system ? undefined : form.name,
        description: form.description || null,
        domain: form.domainSlug || undefined,
        range: form.rangeSlug || undefined,
        cardinality_subject: form.cardinalitySubject,
        cardinality_object: form.cardinalityObject,
        symmetric: form.symmetric,
        transitive: form.transitive,
        temporal: form.temporal,
        high_stakes: form.highStakes,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "relations"],
      });
      push({ title: "Relation saved", description: `${form.name} updated.` });
    },
    onError: (e: Error) =>
      push({
        title: "Save failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => ontologyApi.deleteRelation(workspaceId, relation.slug),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "relations"],
      });
      push({ title: "Relation deleted" });
    },
    onError: (e: Error) =>
      push({
        title: "Delete failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const duplicateMutation = useMutation({
    mutationFn: async () => {
      const base = `${form.slug}_copy`;
      let candidate = base;
      let n = 1;
      while (relations.some((r) => r.slug === candidate)) {
        candidate = `${base}_${n++}`;
      }
      return ontologyApi.createRelation(workspaceId, {
        name: `${form.name} (copy)`,
        slug: candidate,
        description: form.description || null,
        domain: form.domainSlug || undefined,
        range: form.rangeSlug || undefined,
        cardinality_subject: form.cardinalitySubject,
        cardinality_object: form.cardinalityObject,
        inverse_of: form.inverseOfSlug || null,
        symmetric: form.symmetric,
        transitive: form.transitive,
        temporal: form.temporal,
        high_stakes: form.highStakes,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "relations"],
      });
      push({ title: "Relation duplicated" });
    },
    onError: (e: Error) =>
      push({
        title: "Duplicate failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const onDelete = () => {
    if (relation.system) return;
    if (
      typeof window !== "undefined" &&
      !window.confirm(`Delete the ${relation.name} relation?`)
    ) {
      return;
    }
    deleteMutation.mutate();
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-xl">
            {relation.name}
            {relation.system && <Badge variant="outline">system</Badge>}
          </CardTitle>
          <p className="font-mono text-xs text-muted-foreground">
            {relation.slug}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => duplicateMutation.mutate()}
            disabled={duplicateMutation.isPending}
          >
            <Copy /> Duplicate
          </Button>
          {relation.system ? (
            <span
              className="inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs text-muted-foreground"
              title="System relations can't be deleted."
            >
              <Lock className="h-3 w-3" /> System
            </span>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={onDelete}
              disabled={deleteMutation.isPending}
              className="border-destructive/40 text-destructive hover:bg-destructive/10"
            >
              <Trash /> Delete
            </Button>
          )}
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            <Save /> Save
          </Button>
        </div>
      </CardHeader>

      <CardContent className="flex-1 space-y-5 overflow-y-auto">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="rel-name">Name</Label>
            <Input
              id="rel-name"
              value={form.name}
              disabled={relation.system}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rel-slug">Slug</Label>
            <Input id="rel-slug" value={form.slug} disabled />
          </div>
        </div>

        <div className="space-y-1">
          <Label htmlFor="rel-desc">Description</Label>
          <Textarea
            id="rel-desc"
            value={form.description}
            onChange={(e) =>
              setForm((f) => ({ ...f, description: e.target.value }))
            }
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="rel-domain">Domain (subject type)</Label>
            <Select
              id="rel-domain"
              value={form.domainSlug}
              onChange={(e) =>
                setForm((f) => ({ ...f, domainSlug: e.target.value }))
              }
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
            <Label htmlFor="rel-range">Range (object type)</Label>
            <Select
              id="rel-range"
              value={form.rangeSlug}
              onChange={(e) =>
                setForm((f) => ({ ...f, rangeSlug: e.target.value }))
              }
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
            <Label htmlFor="rel-card-subj">Cardinality (subject)</Label>
            <Select
              id="rel-card-subj"
              value={form.cardinalitySubject}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  cardinalitySubject: e.target.value as "one" | "many",
                }))
              }
            >
              <option value="one">one</option>
              <option value="many">many</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="rel-card-obj">Cardinality (object)</Label>
            <Select
              id="rel-card-obj"
              value={form.cardinalityObject}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  cardinalityObject: e.target.value as "one" | "many",
                }))
              }
            >
              <option value="one">one</option>
              <option value="many">many</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1">
          <Label htmlFor="rel-inverse">Inverse of</Label>
          <Select
            id="rel-inverse"
            value={form.inverseOfSlug}
            disabled
            onChange={(e) =>
              setForm((f) => ({ ...f, inverseOfSlug: e.target.value }))
            }
          >
            <option value="">(none)</option>
            {relations
              .filter((r) => r.slug !== relation.slug)
              .map((r) => (
                <option key={r.id} value={r.slug}>
                  {r.name}
                </option>
              ))}
          </Select>
          <p className="text-xs text-muted-foreground">
            Set when the relation is first created — not editable afterwards.
          </p>
        </div>

        <div className="rounded-lg border bg-muted/40 p-4">
          <div className="mb-3 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Flags
          </div>
          <div className="grid gap-4 md:grid-cols-2 md:gap-x-8">
            <ToggleRow
              label="Symmetric"
              description="If A rel B, then B rel A."
              checked={form.symmetric}
              onChange={(v) => setForm((f) => ({ ...f, symmetric: v }))}
            />
            <ToggleRow
              label="Transitive"
              description="If A rel B and B rel C, then A rel C."
              checked={form.transitive}
              onChange={(v) => setForm((f) => ({ ...f, transitive: v }))}
            />
            <ToggleRow
              label="Temporal"
              description="Relation has valid-from / valid-to windows."
              checked={form.temporal}
              onChange={(v) => setForm((f) => ({ ...f, temporal: v }))}
            />
            <ToggleRow
              label="High stakes"
              description="Run the contradictor on edits; extra confirmation."
              checked={form.highStakes}
              onChange={(v) => setForm((f) => ({ ...f, highStakes: v }))}
            />
          </div>
        </div>
      </CardContent>
    </Card>
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
