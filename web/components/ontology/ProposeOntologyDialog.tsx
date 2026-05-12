"use client";
import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  PiCheck as Check,
  PiPlus as Plus,
  PiSparkle as Sparkles,
  PiMagicWand as Wand2,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ontologyApi } from "@/lib/api/endpoints";
import type { OntologyProposal } from "@/lib/api/types";
import { cn } from "@/lib/utils";

interface ProposeOntologyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
}

export function ProposeOntologyDialog({
  open,
  onOpenChange,
  workspaceId,
}: ProposeOntologyDialogProps) {
  const { push } = useToast();
  const qc = useQueryClient();

  const [samples, setSamples] = React.useState("");
  const [apply, setApply] = React.useState(false);
  const [proposal, setProposal] = React.useState<OntologyProposal | null>(null);
  const [addedTypes, setAddedTypes] = React.useState<Set<string>>(new Set());
  const [addedRelations, setAddedRelations] = React.useState<Set<string>>(
    new Set(),
  );

  React.useEffect(() => {
    if (!open) {
      setSamples("");
      setApply(false);
      setProposal(null);
      setAddedTypes(new Set());
      setAddedRelations(new Set());
    }
  }, [open]);

  const proposeMutation = useMutation({
    mutationFn: async () => {
      const chunks = samples
        .split(/\n{2,}/)
        .map((s) => s.trim())
        .filter(Boolean);
      return ontologyApi.propose(workspaceId, {
        samples: chunks.length ? chunks : [samples.trim()].filter(Boolean),
        apply,
      });
    },
    onSuccess: (data) => {
      setProposal(data.proposal);
      if (apply) {
        void qc.invalidateQueries({ queryKey: ["ontology", workspaceId] });
        push({
          title: "Ontology applied",
          description: `${data.proposal.entity_types.length} types, ${data.proposal.relation_types.length} relations.`,
        });
        onOpenChange(false);
      } else {
        push({
          title: "Proposal ready",
          description: "Review and add the items you want.",
        });
      }
    },
    onError: (e: Error) =>
      push({
        title: "Proposal failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const addTypeMutation = useMutation({
    mutationFn: async (type: OntologyProposal["entity_types"][number]) => {
      const schema = buildSchemaFromProposal(type.properties);
      return ontologyApi.createType(workspaceId, {
        name: type.name,
        slug: type.slug,
        extends: type.extends ?? null,
        description: type.description || null,
        schema,
      });
    },
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "types"],
      });
      setAddedTypes((prev) => new Set(prev).add(variables.slug));
      push({ title: "Type added", description: variables.name });
    },
    onError: (e: Error) =>
      push({
        title: "Add type failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const addRelationMutation = useMutation({
    mutationFn: (rel: OntologyProposal["relation_types"][number]) =>
      ontologyApi.createRelation(workspaceId, {
        name: rel.name,
        slug: rel.slug,
        description: rel.description || null,
        domain: rel.domain || undefined,
        range: rel.range || undefined,
        cardinality_subject: rel.cardinality_subject,
        cardinality_object: rel.cardinality_object,
        symmetric: rel.symmetric,
        transitive: rel.transitive,
        temporal: rel.temporal,
        high_stakes: rel.high_stakes,
      }),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({
        queryKey: ["ontology", workspaceId, "relations"],
      });
      setAddedRelations((prev) => new Set(prev).add(variables.slug));
      push({ title: "Relation added", description: variables.name });
    },
    onError: (e: Error) =>
      push({
        title: "Add relation failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const hasProposal = !!proposal;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wand2 className="h-5 w-5 text-primary" />
            Propose ontology with AI
          </DialogTitle>
          <DialogDescription>
            Paste notes, emails, or transcripts. An LLM will infer a
            domain-specific ontology — entity types, their properties, and the
            relations between them.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[65vh] space-y-5 overflow-y-auto pr-1">
          <div className="space-y-2">
            <Label htmlFor="samples">Sample text</Label>
            <Textarea
              id="samples"
              value={samples}
              onChange={(e) => setSamples(e.target.value)}
              placeholder={SAMPLE_PLACEHOLDER}
              className="min-h-[180px] font-mono text-xs"
              disabled={proposeMutation.isPending}
            />
            <p className="text-xs text-muted-foreground">
              Separate multiple samples with a blank line.
            </p>
          </div>

          <div className="flex items-center justify-between rounded-md border p-3">
            <label className="flex items-start gap-3">
              <Switch
                checked={apply}
                onChange={(e) => setApply(e.target.checked)}
                disabled={proposeMutation.isPending}
              />
              <div>
                <div className="text-sm font-medium">Apply immediately</div>
                <p className="text-xs text-muted-foreground">
                  Skip review and create every proposed type and relation.
                </p>
              </div>
            </label>
            <Button
              onClick={() => proposeMutation.mutate()}
              disabled={!samples.trim() || proposeMutation.isPending}
            >
              <Sparkles />
              {proposeMutation.isPending ? "Thinking..." : "Propose"}
            </Button>
          </div>

          {hasProposal && proposal && (
            <div className="space-y-4">
              <Separator />
              {proposal.rationale && (
                <div className="rounded-md border bg-muted/30 p-3 text-sm">
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Rationale
                  </div>
                  <p className="text-sm">{proposal.rationale}</p>
                </div>
              )}

              <section>
                <h3 className="mb-2 text-sm font-semibold">
                  Entity types ({proposal.entity_types.length})
                </h3>
                {proposal.entity_types.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No new types suggested.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {proposal.entity_types.map((t) => {
                      const added = addedTypes.has(t.slug);
                      return (
                        <div key={t.slug} className="rounded-lg border p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="font-medium">{t.name}</span>
                                <code className="text-xs text-muted-foreground">
                                  {t.slug}
                                </code>
                                {t.extends && (
                                  <Badge variant="outline">
                                    extends {t.extends}
                                  </Badge>
                                )}
                              </div>
                              {t.description && (
                                <p className="mt-1 text-xs text-muted-foreground">
                                  {t.description}
                                </p>
                              )}
                              {t.properties.length > 0 && (
                                <div className="mt-2 flex flex-wrap gap-1">
                                  {t.properties.map((p) => (
                                    <span
                                      key={p.name}
                                      className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-1.5 py-0.5 text-[11px]"
                                    >
                                      <span className="font-mono">
                                        {p.name}
                                      </span>
                                      <span className="text-muted-foreground">
                                        :{p.type}
                                      </span>
                                      {p.required && (
                                        <span className="text-destructive">
                                          *
                                        </span>
                                      )}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                            <Button
                              size="sm"
                              variant={added ? "secondary" : "outline"}
                              onClick={() => addTypeMutation.mutate(t)}
                              disabled={added || addTypeMutation.isPending}
                              className={cn(added && "pointer-events-none")}
                            >
                              {added ? <Check /> : <Plus />}
                              {added ? "Added" : "Add"}
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>

              <section>
                <h3 className="mb-2 text-sm font-semibold">
                  Relations ({proposal.relation_types.length})
                </h3>
                {proposal.relation_types.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No new relations suggested.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {proposal.relation_types.map((r) => {
                      const added = addedRelations.has(r.slug);
                      return (
                        <div key={r.slug} className="rounded-lg border p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-medium">{r.name}</span>
                                <code className="text-xs text-muted-foreground">
                                  {r.slug}
                                </code>
                                <span className="text-xs text-muted-foreground">
                                  <span className="font-mono">
                                    {r.domain || "any"}
                                  </span>
                                  {" → "}
                                  <span className="font-mono">
                                    {r.range || "any"}
                                  </span>
                                </span>
                              </div>
                              {r.description && (
                                <p className="mt-1 text-xs text-muted-foreground">
                                  {r.description}
                                </p>
                              )}
                              <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
                                {r.symmetric && <ChipMini>symmetric</ChipMini>}
                                {r.transitive && (
                                  <ChipMini>transitive</ChipMini>
                                )}
                                {r.temporal && <ChipMini>temporal</ChipMini>}
                                {r.high_stakes && (
                                  <ChipMini tone="warn">high-stakes</ChipMini>
                                )}
                              </div>
                            </div>
                            <Button
                              size="sm"
                              variant={added ? "secondary" : "outline"}
                              onClick={() => addRelationMutation.mutate(r)}
                              disabled={added || addRelationMutation.isPending}
                            >
                              {added ? <Check /> : <Plus />}
                              {added ? "Added" : "Add"}
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChipMini({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "warn";
}) {
  return (
    <span
      className={cn(
        "inline-flex h-4 items-center rounded-full border px-1.5 font-medium",
        tone === "warn"
          ? "border-amber-400/50 bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          : "bg-muted text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

function buildSchemaFromProposal(
  properties: OntologyProposal["entity_types"][number]["properties"],
): Record<string, unknown> {
  const props: Record<string, unknown> = {};
  const required: string[] = [];

  for (const p of properties) {
    const entry: Record<string, unknown> = { title: p.label || p.name };
    const type = (p.type || "string").toLowerCase();
    if (Array.isArray(p.enum_values) && p.enum_values.length > 0) {
      entry.type = "string";
      entry.enum = p.enum_values;
    } else if (type === "integer") {
      entry.type = "integer";
    } else if (type === "number") {
      entry.type = "number";
    } else if (type === "boolean") {
      entry.type = "boolean";
    } else if (type === "date") {
      entry.type = "string";
      entry.format = "date";
    } else if (type === "date-time" || type === "datetime") {
      entry.type = "string";
      entry.format = "date-time";
    } else {
      entry.type = "string";
    }
    props[p.name] = entry;
    if (p.required) required.push(p.name);
  }

  const schema: Record<string, unknown> = { type: "object", properties: props };
  if (required.length > 0) schema.required = required;
  return schema;
}

const SAMPLE_PLACEHOLDER = `Paste a meeting note, email, or transcript. For example:

Kickoff call with Acme. Sarah (VP Eng) will sponsor. Target rollout: Q3.
Mike (CTO) requested SOC2 report. Annual contract, $120k.

Second email thread:
From: Priya - Data scientist at Globex, joined from Initech last year.
Working on the churn model. Uses BigQuery.`;
