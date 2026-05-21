"use client";
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  PiStack as Layers,
  PiList as List,
  PiGraph as Network,
  PiPlus as Plus,
  PiTag as TagIcon,
  PiMagicWand as Wand2,
} from "react-icons/pi";

import { LabelManager } from "@/components/labels/LabelManager";
import { LabelPolicyEditor } from "@/components/labels/LabelPolicyEditor";
import type { EntityType, RelationType } from "@/lib/api/types";
import { RelationCreateDialog } from "@/components/ontology/RelationCreateDialog";
import { RelationEditor } from "@/components/ontology/RelationEditor";
import { RelationList } from "@/components/ontology/RelationList";
import { ProposeOntologyDialog } from "@/components/ontology/ProposeOntologyDialog";
import { TypeCreateDialog } from "@/components/ontology/TypeCreateDialog";
import { TypeEditor } from "@/components/ontology/TypeEditor";
import { TypeHierarchyTree } from "@/components/ontology/TypeHierarchyTree";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ontologyApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function OntologyPage() {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? "";

  const typesQuery = useQuery({
    queryKey: ["ontology", workspaceId, "types"],
    queryFn: () => ontologyApi.listTypes(workspaceId),
    enabled: !!workspaceId,
  });
  const relationsQuery = useQuery({
    queryKey: ["ontology", workspaceId, "relations"],
    queryFn: () => ontologyApi.listRelations(workspaceId),
    enabled: !!workspaceId,
  });

  const types = React.useMemo(() => typesQuery.data ?? [], [typesQuery.data]);
  const relations = React.useMemo(
    () => relationsQuery.data ?? [],
    [relationsQuery.data],
  );

  const [selectedTypeSlug, setSelectedTypeSlug] = React.useState<string | null>(
    null,
  );
  const [selectedRelationSlug, setSelectedRelationSlug] = React.useState<
    string | null
  >(null);
  const [createTypeOpen, setCreateTypeOpen] = React.useState(false);
  const [createRelationOpen, setCreateRelationOpen] = React.useState(false);
  const [proposeOpen, setProposeOpen] = React.useState(false);

  // Auto-select the first non-system type on load
  React.useEffect(() => {
    if (!selectedTypeSlug && types.length > 0) {
      const firstCustom = types.find((t) => !t.system) ?? types[0];
      if (firstCustom) setSelectedTypeSlug(firstCustom.slug);
    }
  }, [types, selectedTypeSlug]);
  React.useEffect(() => {
    if (!selectedRelationSlug && relations.length > 0) {
      const firstCustom = relations.find((r) => !r.system) ?? relations[0];
      if (firstCustom) setSelectedRelationSlug(firstCustom.slug);
    }
  }, [relations, selectedRelationSlug]);

  const selectedType = types.find((t) => t.slug === selectedTypeSlug) ?? null;
  const selectedRelation =
    relations.find((r) => r.slug === selectedRelationSlug) ?? null;

  const hasCustomTypes = types.some((t) => !t.system);

  if (!workspace) {
    return (
      <main className="mx-auto max-w-5xl p-8">
        <EmptyState
          icon={Layers}
          title="No workspace"
          description="Select or create a workspace to edit its ontology."
        />
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-full min-h-[calc(100vh-6rem)] max-w-7xl flex-col gap-6 p-4 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Ontology</h1>
          <p className="text-sm text-muted-foreground">
            Define the entity types and relations your workspace understands.
            Humans edit here; agents read and extend the same schema via MCP.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setProposeOpen(true)}>
            <Wand2 /> Propose with AI
          </Button>
        </div>
      </header>

      <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="overview">
              <List className="mr-1.5 h-3.5 w-3.5" />
              Overview
            </TabsTrigger>
            <TabsTrigger value="types">
              <Layers className="mr-1.5 h-3.5 w-3.5" />
              Entity types
              <span className="ml-2 rounded-full bg-muted-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
                {types.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="relations">
              <Network className="mr-1.5 h-3.5 w-3.5" />
              Relations
              <span className="ml-2 rounded-full bg-muted-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
                {relations.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="labels">
              <TagIcon className="mr-1.5 h-3.5 w-3.5" />
              Labels
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent
          value="overview"
          className="mt-4 flex min-h-0 flex-1 flex-col gap-4 overflow-auto"
        >
          <OntologyOverview types={types} relations={relations} />
        </TabsContent>

        <TabsContent
          value="types"
          className="mt-4 flex min-h-0 flex-1 flex-col gap-3"
        >
          {!hasCustomTypes && types.length > 0 && (
            <BuiltinBanner
              count={types.length}
              label="built-in entity types"
              onCreate={() => setCreateTypeOpen(true)}
              onPropose={() => setProposeOpen(true)}
            />
          )}
          <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-[320px_minmax(0,1fr)]">
            <Card className="flex min-h-0 flex-col overflow-hidden">
              <div className="flex items-center justify-between border-b p-3">
                <div className="text-sm font-semibold">Types</div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setCreateTypeOpen(true)}
                >
                  <Plus /> New
                </Button>
              </div>
              <TypeHierarchyTree
                types={types}
                selectedSlug={selectedTypeSlug}
                onSelect={(t) => setSelectedTypeSlug(t.slug)}
              />
            </Card>

            <div className="min-h-0">
              {selectedType ? (
                <TypeEditor
                  key={selectedType.id}
                  type={selectedType}
                  allTypes={types}
                  workspaceId={workspaceId}
                />
              ) : (
                <EmptyState
                  icon={Layers}
                  title="Select a type"
                  description="Pick a type from the list, or create a new one."
                />
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent
          value="relations"
          className="mt-4 flex min-h-0 flex-1 flex-col gap-3"
        >
          {relations.length > 0 && !relations.some((r) => !r.system) && (
            <BuiltinBanner
              count={relations.length}
              label="built-in relations"
              onCreate={() => setCreateRelationOpen(true)}
              onPropose={() => setProposeOpen(true)}
            />
          )}
          <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-[320px_minmax(0,1fr)]">
            <Card className="flex min-h-0 flex-col overflow-hidden">
              <div className="flex items-center justify-between border-b p-3">
                <div className="text-sm font-semibold">Relations</div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setCreateRelationOpen(true)}
                >
                  <Plus /> New
                </Button>
              </div>
              <RelationList
                relations={relations}
                types={types}
                selectedSlug={selectedRelationSlug}
                onSelect={(r) => setSelectedRelationSlug(r.slug)}
              />
            </Card>

            <div className="min-h-0">
              {selectedRelation ? (
                <RelationEditor
                  key={selectedRelation.id}
                  relation={selectedRelation}
                  types={types}
                  relations={relations}
                  workspaceId={workspaceId}
                />
              ) : (
                <EmptyState
                  icon={Network}
                  title="Select a relation"
                  description="Pick a relation from the list, or create a new one."
                />
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent
          value="labels"
          className="mt-4 flex min-h-0 flex-1 flex-col gap-6"
        >
          <LabelManager workspaceId={workspaceId} />
          <LabelPolicyEditor workspaceId={workspaceId} />
        </TabsContent>
      </Tabs>

      <TypeCreateDialog
        open={createTypeOpen}
        onOpenChange={setCreateTypeOpen}
        allTypes={types}
        workspaceId={workspaceId}
        onCreated={(t) => setSelectedTypeSlug(t.slug)}
      />
      <RelationCreateDialog
        open={createRelationOpen}
        onOpenChange={setCreateRelationOpen}
        types={types}
        relations={relations}
        workspaceId={workspaceId}
        onCreated={(r) => setSelectedRelationSlug(r.slug)}
      />
      <ProposeOntologyDialog
        open={proposeOpen}
        onOpenChange={setProposeOpen}
        workspaceId={workspaceId}
      />
    </main>
  );
}

function BuiltinBanner({
  count,
  label,
  onCreate,
  onPropose,
}: {
  count: number;
  label: string;
  onCreate: () => void;
  onPropose: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/40 px-4 py-3 text-sm">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Layers className="h-4 w-4" />
        <span>
          You&apos;re viewing the{" "}
          <strong className="text-foreground">{count}</strong> {label}. Add your
          own to shape this workspace.
        </span>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={onPropose}>
          <Wand2 className="h-3.5 w-3.5" /> Propose with AI
        </Button>
        <Button size="sm" onClick={onCreate}>
          <Plus className="h-3.5 w-3.5" /> New
        </Button>
      </div>
    </div>
  );
}

/**
 * Compact "at-a-glance" view of the workspace ontology.
 *
 * Two side-by-side lists: every entity type (with parent + system badge)
 * and every relation (with domain → range + flags). No editing here — the
 * Types/Relations tabs handle that. This tab is purely "show me everything
 * in one screen so I understand the schema."
 */
function OntologyOverview({
  types,
  relations,
}: {
  types: EntityType[];
  relations: RelationType[];
}) {
  const typeById = React.useMemo(() => {
    const m = new Map<string, EntityType>();
    for (const t of types) m.set(t.id, t);
    return m;
  }, [types]);

  // Stable sort: system first, then alphabetical by name.
  const sortedTypes = React.useMemo(
    () =>
      [...types].sort((a, b) => {
        if (a.system !== b.system) return a.system ? -1 : 1;
        return a.name.localeCompare(b.name);
      }),
    [types],
  );
  const sortedRelations = React.useMemo(
    () =>
      [...relations].sort((a, b) => {
        if (a.system !== b.system) return a.system ? -1 : 1;
        return a.name.localeCompare(b.name);
      }),
    [relations],
  );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Types */}
      <Card className="flex flex-col overflow-hidden">
        <div className="border-b p-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">Entity types</div>
            <span className="text-xs text-muted-foreground">
              {types.length} total · {types.filter((t) => !t.system).length}{" "}
              custom
            </span>
          </div>
        </div>
        {sortedTypes.length === 0 ? (
          <EmptyState
            icon={Layers}
            title="No entity types yet"
            description="Switch to the Entity types tab to create one."
          />
        ) : (
          <ul className="divide-y text-sm">
            {sortedTypes.map((t) => {
              const parent = t.extends_id ? typeById.get(t.extends_id) : null;
              return (
                <li key={t.id} className="flex items-start gap-2 px-3 py-2">
                  <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{t.name}</span>
                      <code className="text-[10px] text-muted-foreground">
                        {t.slug}
                      </code>
                      {parent && (
                        <span className="text-[10px] text-muted-foreground">
                          extends <code>{parent.slug}</code>
                        </span>
                      )}
                      {t.system && (
                        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          built-in
                        </span>
                      )}
                    </div>
                    {t.description && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {t.description}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {/* Relations */}
      <Card className="flex flex-col overflow-hidden">
        <div className="border-b p-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">Relations</div>
            <span className="text-xs text-muted-foreground">
              {relations.length} total ·{" "}
              {relations.filter((r) => !r.system).length} custom
            </span>
          </div>
        </div>
        {sortedRelations.length === 0 ? (
          <EmptyState
            icon={Network}
            title="No relations yet"
            description="Switch to the Relations tab to create one."
          />
        ) : (
          <ul className="divide-y text-sm">
            {sortedRelations.map((r) => {
              const domain = r.domain_type_id
                ? typeById.get(r.domain_type_id)
                : null;
              const range = r.range_type_id
                ? typeById.get(r.range_type_id)
                : null;
              return (
                <li key={r.id} className="flex items-start gap-2 px-3 py-2">
                  <Network className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.name}</span>
                      <code className="text-[10px] text-muted-foreground">
                        {r.slug}
                      </code>
                      {(domain || range) && (
                        <span className="text-[10px] text-muted-foreground">
                          <code>{domain?.slug ?? "?"}</code>
                          {" → "}
                          <code>{range?.slug ?? "?"}</code>
                        </span>
                      )}
                      {r.system && (
                        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          built-in
                        </span>
                      )}
                      {r.high_stakes && (
                        <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-300">
                          high-stakes
                        </span>
                      )}
                      {r.symmetric && (
                        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          symmetric
                        </span>
                      )}
                      {r.transitive && (
                        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          transitive
                        </span>
                      )}
                    </div>
                    {r.description && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {r.description}
                      </p>
                    )}
                    <div className="mt-0.5 text-[10px] text-muted-foreground">
                      cardinality {r.cardinality_subject} →{" "}
                      {r.cardinality_object}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
