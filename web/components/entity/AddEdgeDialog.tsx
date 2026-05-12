"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { edgesApi, entitiesApi, ontologyApi } from "@/lib/api/endpoints";
import type { Entity } from "@/lib/api/types";

export function AddEdgeDialog({
  workspaceId,
  subject,
  trigger,
}: {
  workspaceId: string;
  subject: Entity;
  trigger: React.ReactNode;
}) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [open, setOpen] = useState(false);
  const [predicate, setPredicate] = useState("");
  const [query, setQuery] = useState("");
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [fact, setFact] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const relations = useQuery({
    queryKey: ["ontology", workspaceId, "relations"],
    queryFn: () => ontologyApi.listRelations(workspaceId),
    enabled: open,
  });
  const objectOptions = useQuery({
    queryKey: ["entities", workspaceId, { q: query }],
    queryFn: () => entitiesApi.list(workspaceId, { query, limit: 15 }),
    enabled: open && query.length >= 1,
  });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!predicate || !selectedObjectId) return;
    setSubmitting(true);
    try {
      await edgesApi.create(workspaceId, {
        subject_id: subject.id,
        predicate,
        object_id: selectedObjectId,
        fact: fact || null,
      });
      push({ title: "Edge added" });
      void qc.invalidateQueries({
        queryKey: ["entity-edges", workspaceId, subject.id],
      });
      void qc.invalidateQueries({
        queryKey: ["entity-history", workspaceId, subject.id],
      });
      setOpen(false);
      setPredicate("");
      setSelectedObjectId(null);
      setQuery("");
      setFact("");
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

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a fact about {subject.canonical}</DialogTitle>
          <DialogDescription>
            The relation's domain/range and cardinality will be validated.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-3">
          <div className="space-y-1">
            <Label>Predicate</Label>
            <Select
              value={predicate}
              onChange={(e) => setPredicate(e.target.value)}
              required
            >
              <option value="">Select a relation…</option>
              {(relations.data ?? []).map((r) => (
                <option key={r.id} value={r.slug}>
                  {r.name} ({r.slug})
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-1">
            <Label>Object</Label>
            <Input
              placeholder="Search entities…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSelectedObjectId(null);
              }}
            />
            {objectOptions.data &&
              objectOptions.data.length > 0 &&
              !selectedObjectId && (
                <ul className="max-h-40 overflow-auto rounded-md border">
                  {objectOptions.data.map((o) => (
                    <li key={o.id}>
                      <button
                        type="button"
                        className="flex w-full items-center justify-between px-2 py-1.5 text-left text-sm hover:bg-accent"
                        onClick={() => {
                          setSelectedObjectId(o.id);
                          setQuery(o.canonical);
                        }}
                      >
                        <span>{o.canonical}</span>
                        <span className="text-xs text-muted-foreground">
                          {o.type_slug}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
          </div>

          <div className="space-y-1">
            <Label>Fact (optional)</Label>
            <Input
              placeholder={`e.g. ${subject.canonical} …`}
              value={fact}
              onChange={(e) => setFact(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting || !predicate || !selectedObjectId}
            >
              {submitting ? "Adding…" : "Add"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
