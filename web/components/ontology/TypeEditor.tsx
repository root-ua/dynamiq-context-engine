"use client";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import {
  PiFloppyDisk as Save,
  PiTrash as Trash,
  PiLock as Lock,
  PiCopy as Copy,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { entitiesApi, ontologyApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";
import type { EntityType } from "@/lib/api/types";
import { SchemaEditor } from "./SchemaEditor";

interface TypeEditorProps {
  type: EntityType;
  allTypes: EntityType[];
  workspaceId: string;
}

interface FormState {
  name: string;
  slug: string;
  extendsSlug: string;
  description: string;
  icon: string;
  color: string;
  schema: Record<string, unknown>;
}

function initialFormState(type: EntityType, allTypes: EntityType[]): FormState {
  const parent = allTypes.find((t) => t.id === type.extends_id);
  const uiHints = (type.ui_hints ?? {}) as { icon?: string; color?: string };
  return {
    name: type.name,
    slug: type.slug,
    extendsSlug: parent?.slug ?? "",
    description: type.description ?? "",
    icon: uiHints.icon ?? "",
    color: uiHints.color ?? "",
    schema: type.schema ?? { type: "object", properties: {} },
  };
}

export function TypeEditor({ type, allTypes, workspaceId }: TypeEditorProps) {
  const { push } = useToast();
  const qc = useQueryClient();
  const [form, setForm] = React.useState<FormState>(() =>
    initialFormState(type, allTypes),
  );

  React.useEffect(() => {
    setForm(initialFormState(type, allTypes));
  }, [type, allTypes]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const patch: Parameters<typeof ontologyApi.updateType>[2] = {
        schema: form.schema,
        ui_hints: {
          icon: form.icon || undefined,
          color: form.color || undefined,
        },
        description: form.description || null,
      };
      if (!type.system) {
        patch.name = form.name;
        patch.extends = form.extendsSlug || null;
      }
      return ontologyApi.updateType(workspaceId, type.slug, patch);
    },
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "types"],
      });
      push({ title: "Type saved", description: `${form.name} updated.` });
    },
    onError: (e: Error) =>
      push({
        title: "Save failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => ontologyApi.deleteType(workspaceId, type.slug),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "types"],
      });
      push({ title: "Type deleted" });
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
      while (allTypes.some((t) => t.slug === candidate)) {
        candidate = `${base}_${n++}`;
      }
      return ontologyApi.createType(workspaceId, {
        name: `${form.name} (copy)`,
        slug: candidate,
        extends: form.extendsSlug || type.slug,
        schema: form.schema,
        description: form.description || null,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "types"],
      });
      push({ title: "Type duplicated" });
    },
    onError: (e: Error) =>
      push({
        title: "Duplicate failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const usageQuery = useQuery({
    queryKey: ["ontology", workspaceId, "type-usage", type.slug],
    queryFn: () =>
      entitiesApi.list(workspaceId, { type: type.slug, limit: 200 }),
  });
  const usageCount = usageQuery.data?.length ?? null;

  const onDelete = () => {
    if (type.system) return;
    if (
      typeof window !== "undefined" &&
      !window.confirm(`Delete the ${type.name} type? This cannot be undone.`)
    ) {
      return;
    }
    deleteMutation.mutate();
  };

  const parentOptions = React.useMemo(
    () => allTypes.filter((t) => t.slug !== type.slug),
    [allTypes, type.slug],
  );

  const previewSchema = React.useMemo(() => {
    const s = form.schema ?? {};
    if (typeof s !== "object" || Array.isArray(s))
      return { type: "object", properties: {} };
    return { ...s, type: "object" };
  }, [form.schema]);

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-xl">
            {type.name}
            {type.system && <Badge variant="outline">system</Badge>}
          </CardTitle>
          <p className="font-mono text-xs text-muted-foreground">
            {type.hierarchy}
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
          {type.system ? (
            <span
              className="inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs text-muted-foreground"
              title="System types can't be deleted."
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

      <CardContent className="flex-1 overflow-y-auto">
        <Tabs defaultValue="schema" className="w-full">
          <TabsList>
            <TabsTrigger value="schema">Schema</TabsTrigger>
            <TabsTrigger value="metadata">Metadata</TabsTrigger>
            <TabsTrigger value="usage">Usage</TabsTrigger>
          </TabsList>

          <TabsContent value="schema">
            <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div>
                <h4 className="mb-3 text-sm font-semibold">Definition</h4>
                <SchemaEditor
                  value={form.schema}
                  onChange={(next) => setForm((f) => ({ ...f, schema: next }))}
                />
              </div>
              <div>
                <h4 className="mb-3 text-sm font-semibold">Live preview</h4>
                <div className="rounded-lg border p-4">
                  <SchemaPreview schema={previewSchema} />
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="metadata">
            <div className="max-w-2xl space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="type-name">Name</Label>
                  <Input
                    id="type-name"
                    value={form.name}
                    disabled={type.system}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, name: e.target.value }))
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="type-slug">Slug</Label>
                  <Input id="type-slug" value={form.slug} disabled />
                </div>
              </div>

              <div className="space-y-1">
                <Label htmlFor="type-extends">Extends</Label>
                <Select
                  id="type-extends"
                  value={form.extendsSlug}
                  disabled={type.system}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, extendsSlug: e.target.value }))
                  }
                >
                  <option value="">(no parent)</option>
                  {parentOptions.map((t) => (
                    <option key={t.id} value={t.slug}>
                      {t.name} ({t.hierarchy})
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1">
                <Label htmlFor="type-description">Description</Label>
                <Textarea
                  id="type-description"
                  value={form.description}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, description: e.target.value }))
                  }
                />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="type-icon">Icon</Label>
                  <Input
                    id="type-icon"
                    placeholder="e.g. user, briefcase"
                    value={form.icon}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, icon: e.target.value }))
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="type-color">Color</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="type-color"
                      placeholder="#10b981"
                      value={form.color}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, color: e.target.value }))
                      }
                    />
                    <div
                      className={cn(
                        "h-6 w-6 rounded border",
                        !form.color && "bg-muted",
                      )}
                      style={
                        form.color ? { backgroundColor: form.color } : undefined
                      }
                    />
                  </div>
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="usage">
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                Entities of this type in the workspace.
              </p>
              <div className="rounded-lg border p-4">
                <div className="text-sm">
                  entities:{" "}
                  <span className="font-mono">
                    {usageQuery.isLoading
                      ? "..."
                      : usageCount === null
                        ? "—"
                        : String(usageCount)}
                  </span>
                </div>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function SchemaPreview({ schema }: { schema: Record<string, unknown> }) {
  const [formData, setFormData] = React.useState<unknown>({});
  const hasProps =
    schema &&
    typeof schema === "object" &&
    schema.properties &&
    Object.keys(schema.properties).length > 0;

  if (!hasProps) {
    return (
      <p className="text-sm text-muted-foreground">
        Add at least one property to see a live preview.
      </p>
    );
  }

  return (
    <Form
      schema={schema}
      validator={validator}
      formData={formData}
      onChange={(e) => setFormData(e.formData)}
      liveValidate
      tagName="div"
      uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
    />
  );
}
