"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PiPlus as Plus, PiMagnifyingGlass as Search } from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { entitiesApi, ontologyApi } from "@/lib/api/endpoints";
import { formatDate } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

export default function EntitiesPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const router = useRouter();
  const { push } = useToast();

  const [typeFilter, setTypeFilter] = useState<string>("");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newType, setNewType] = useState("");
  const [newName, setNewName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const types = useQuery({
    queryKey: ["ontology", wsId, "types"],
    queryFn: () => ontologyApi.listTypes(wsId),
    enabled: !!wsId,
  });

  const entities = useQuery({
    queryKey: ["entities", wsId, { type: typeFilter, q: query }],
    queryFn: () =>
      entitiesApi.list(wsId, {
        type: typeFilter || undefined,
        query: query || undefined,
        limit: 100,
      }),
    enabled: !!wsId,
  });

  const nonAbstractTypes = (types.data ?? []).filter(
    (t) => !t.ui_hints?.abstract,
  );

  async function createEntity(e: React.FormEvent) {
    e.preventDefault();
    if (!workspace) return;
    setSubmitting(true);
    try {
      const ent = await entitiesApi.create(wsId, {
        type: newType,
        canonical: newName,
      });
      void qc.invalidateQueries({ queryKey: ["entities", wsId] });
      push({ title: "Entity created" });
      setCreateOpen(false);
      setNewName("");
      void router.push(`/${workspace.slug}/entities/${ent.id}`);
    } catch (err: unknown) {
      push({
        title: "Failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  }

  if (!workspace) return null;
  const base = `/${workspace.slug}`;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Entities</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Nodes in your knowledge graph. Identity is stable; edges carry
            history.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" /> New entity
        </Button>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1 space-y-1">
            <Label className="text-xs text-muted-foreground">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-8"
                placeholder="Name or alias…"
              />
            </div>
          </div>
          <div className="space-y-1 sm:w-56">
            <Label className="text-xs text-muted-foreground">Type</Label>
            <Select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">All types</option>
              {(types.data ?? []).map((t) => (
                <option key={t.id} value={t.slug}>
                  {t.name} ({t.slug})
                </option>
              ))}
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {(entities.data ?? []).length === 0 ? (
            <div className="p-6">
              <EmptyState
                title="No entities match"
                description={
                  typeFilter || query
                    ? "Try loosening the filters."
                    : "Create an entity or let an agent extract them from episodes."
                }
                action={
                  <Button onClick={() => setCreateOpen(true)}>
                    <Plus className="h-4 w-4" /> New entity
                  </Button>
                }
              />
            </div>
          ) : (
            <ul className="divide-y">
              {(entities.data ?? []).map((e) => (
                <li key={e.id}>
                  <Link
                    className="flex flex-col gap-1 px-4 py-3 text-sm transition-colors hover:bg-accent sm:flex-row sm:items-center sm:justify-between sm:gap-3"
                    href={`${base}/entities/${e.id}`}
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{e.canonical}</div>
                      {e.aliases.length > 0 && (
                        <div className="truncate text-xs text-muted-foreground">
                          aka {e.aliases.join(", ")}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2 text-xs">
                      {e.type_slug && (
                        <Badge variant="outline" className="text-[11px]">
                          {e.type_slug}
                        </Badge>
                      )}
                      <span className="text-muted-foreground">
                        {formatDate(e.updated_at)}
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New entity</DialogTitle>
            <DialogDescription>
              Pick a type and give it a canonical name.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={createEntity} className="space-y-3">
            <div className="space-y-1">
              <Label>Type</Label>
              <Select
                required
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
              >
                <option value="">Select…</option>
                {nonAbstractTypes.map((t) => (
                  <option key={t.id} value={t.slug}>
                    {t.name} ({t.slug})
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Name</Label>
              <Input
                required
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
