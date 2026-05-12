"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PiArrowLeft as ArrowLeft, PiPlus as Plus } from "react-icons/pi";

import { AddEdgeDialog } from "@/components/entity/AddEdgeDialog";
import { EdgesPanel } from "@/components/entity/EdgesPanel";
import { EntityForm } from "@/components/entity/EntityForm";
import { EntityTimeline } from "@/components/entity/EntityTimeline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { entitiesApi, ontologyApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function EntityDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const { push } = useToast();

  const entity = useQuery({
    queryKey: ["entity", wsId, id],
    queryFn: () => entitiesApi.get(wsId, id),
    enabled: !!wsId && !!id,
  });

  const typeInfo = useQuery({
    queryKey: ["ontology", wsId, "types"],
    queryFn: () => ontologyApi.listTypes(wsId),
    enabled: !!wsId,
  });

  const history = useQuery({
    queryKey: ["entity-history", wsId, id],
    queryFn: () => entitiesApi.history(wsId, id),
    enabled: !!wsId && !!id,
  });

  const backlinks = useQuery({
    queryKey: ["entity-backlinks", wsId, id],
    queryFn: () => entitiesApi.backlinks(wsId, id),
    enabled: !!wsId && !!id,
  });

  async function onSubmit(data: Parameters<typeof entitiesApi.update>[2]) {
    if (!entity.data) return;
    try {
      await entitiesApi.update(wsId, entity.data.id, data);
      push({ title: "Saved" });
      void qc.invalidateQueries({ queryKey: ["entity", wsId, id] });
    } catch (err: unknown) {
      push({
        title: "Failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  }

  if (!workspace || !entity.data) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        {entity.isError ? "Entity not found." : "Loading…"}
      </div>
    );
  }

  const base = `/${workspace.slug}`;
  const type = typeInfo.data?.find((t) => t.id === entity.data.type_id) ?? null;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" asChild>
            <Link href={`${base}/entities`}>
              <ArrowLeft className="h-4 w-4" /> All entities
            </Link>
          </Button>
          <h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
            {entity.data.canonical}
            {entity.data.type_slug && (
              <Badge variant="outline">{entity.data.type_slug}</Badge>
            )}
          </h1>
          {entity.data.iri && (
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {entity.data.iri}
            </p>
          )}
        </div>
        <AddEdgeDialog
          workspaceId={wsId}
          subject={entity.data}
          trigger={
            <Button>
              <Plus className="h-4 w-4" /> Add fact
            </Button>
          }
        />
      </div>

      <Tabs defaultValue="properties">
        <TabsList>
          <TabsTrigger value="properties">Properties</TabsTrigger>
          <TabsTrigger value="edges">Edges</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="backlinks">Backlinks</TabsTrigger>
        </TabsList>

        <TabsContent value="properties">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Edit properties</CardTitle>
            </CardHeader>
            <CardContent>
              <EntityForm
                entity={entity.data}
                type={type}
                onSubmit={onSubmit}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="edges">
          <EdgesPanel
            workspaceId={wsId}
            workspaceSlug={workspace.slug}
            entityId={entity.data.id}
            entityName={entity.data.canonical}
          />
        </TabsContent>

        <TabsContent value="timeline">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">History</CardTitle>
            </CardHeader>
            <CardContent>
              <EntityTimeline events={history.data ?? []} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="backlinks">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Mentions in documents</CardTitle>
            </CardHeader>
            <CardContent>
              {backlinks.data && backlinks.data.length > 0 ? (
                <ul className="divide-y text-sm">
                  {backlinks.data.map((b) => (
                    <li key={b.block_id}>
                      <Link
                        className="flex items-center justify-between gap-3 rounded-md px-2 py-2 hover:bg-accent"
                        href={`${base}/documents/${b.document_id}#block-${b.block_id}`}
                      >
                        <div className="min-w-0">
                          <div className="font-medium">{b.document_title}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {b.search_text}
                          </div>
                        </div>
                        <Badge variant="outline">{b.block_type}</Badge>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  This entity isn't mentioned in any documents yet.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
