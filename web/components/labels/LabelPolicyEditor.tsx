"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PiPlus as Plus, PiTrash as Trash } from "react-icons/pi";

import { LabelBadge } from "@/components/labels/LabelBadge";
import { Badge } from "@/components/ui/badge";
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
import { useToast } from "@/components/ui/toast";
import { labelPoliciesApi, labelsApi } from "@/lib/api/endpoints";
import type {
  Label,
  LabelPolicy,
  LabelPolicyAction,
  LabelPolicyRule,
} from "@/lib/api/types";

interface Props {
  workspaceId: string;
}

type RuleKind = "mutually_exclusive" | "requires_role";

export function LabelPolicyEditor({ workspaceId }: Props) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [createOpen, setCreateOpen] = React.useState(false);

  const policiesQuery = useQuery({
    queryKey: ["label-policies", workspaceId],
    queryFn: () => labelPoliciesApi.list(workspaceId),
    enabled: !!workspaceId,
  });
  const labelsQuery = useQuery({
    queryKey: ["labels", workspaceId],
    queryFn: () => labelsApi.list(workspaceId),
    enabled: !!workspaceId,
  });

  const remove = useMutation({
    mutationFn: (id: string) => labelPoliciesApi.delete(workspaceId, id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["label-policies", workspaceId] });
      push({ title: "Policy removed" });
    },
    onError: (err) =>
      push({
        title: "Failed to remove",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const policies = policiesQuery.data ?? [];
  const labels = labelsQuery.data ?? [];

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Label policies</h2>
          <p className="text-sm text-muted-foreground">
            Rules over labels. Evaluated against every retrieval result.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => setCreateOpen(true)}
          disabled={labels.length === 0}
        >
          <Plus className="h-3.5 w-3.5" /> New policy
        </Button>
      </div>
      {labels.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Create labels first, then come back here to write policies over them.
        </p>
      )}

      {policies.length === 0 ? (
        <EmptyState
          title="No policies yet"
          description="Add a policy to enforce label rules at retrieval time."
        />
      ) : (
        <div className="grid gap-3">
          {policies.map((p) => (
            <PolicyRow
              key={p.id}
              policy={p}
              labels={labels}
              onDelete={() => remove.mutate(p.id)}
              busy={remove.isPending}
            />
          ))}
        </div>
      )}

      <CreatePolicyDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        workspaceId={workspaceId}
        labels={labels}
      />
    </>
  );
}

function PolicyRow({
  policy,
  labels,
  onDelete,
  busy,
}: {
  policy: LabelPolicy;
  labels: Label[];
  onDelete: () => void;
  busy: boolean;
}) {
  const labelLookup = React.useMemo(
    () => new Map(labels.map((l) => [l.slug, l])),
    [labels],
  );
  const rule = policy.rule;
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">{policy.name}</div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge variant="secondary">{rule.kind}</Badge>
              <Badge
                variant={policy.action === "drop" ? "destructive" : "outline"}
              >
                {policy.action}
              </Badge>
              {!policy.enabled && <Badge variant="outline">disabled</Badge>}
            </div>
          </div>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={onDelete}
            aria-label="Delete policy"
          >
            <Trash className="h-3.5 w-3.5" />
          </Button>
        </div>

        {Array.isArray((rule as { labels?: string[] }).labels) && (
          <div className="flex flex-wrap gap-1.5">
            {(rule as { labels: string[] }).labels.map((slug) => {
              const l = labelLookup.get(slug);
              return (
                <LabelBadge
                  key={slug}
                  label={l ?? { slug, name: slug, color: null, id: slug }}
                />
              );
            })}
          </div>
        )}

        {rule.kind === "requires_role" && (
          <div className="text-xs text-muted-foreground">
            Allowed roles:{" "}
            <span className="font-mono">
              {((rule as { roles: string[] }).roles ?? []).join(", ")}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CreatePolicyDialog({
  open,
  onOpenChange,
  workspaceId,
  labels,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceId: string;
  labels: Label[];
}) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<RuleKind>("mutually_exclusive");
  const [selectedLabels, setSelectedLabels] = React.useState<string[]>([]);
  const [roles, setRoles] = React.useState<string[]>(["admin", "owner"]);
  const [action, setAction] = React.useState<LabelPolicyAction>("drop");

  React.useEffect(() => {
    if (!open) {
      setName("");
      setKind("mutually_exclusive");
      setSelectedLabels([]);
      setRoles(["admin", "owner"]);
      setAction("drop");
    }
  }, [open]);

  const create = useMutation({
    mutationFn: () => {
      const rule: LabelPolicyRule =
        kind === "mutually_exclusive"
          ? { kind: "mutually_exclusive", labels: selectedLabels }
          : {
              kind: "requires_role",
              labels: selectedLabels,
              roles,
            };
      return labelPoliciesApi.create(workspaceId, {
        name,
        rule,
        action,
        enabled: true,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["label-policies", workspaceId],
      });
      push({ title: "Policy created" });
      onOpenChange(false);
    },
    onError: (err) =>
      push({
        title: "Create failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const minLabels = kind === "mutually_exclusive" ? 2 : 1;
  const canSubmit =
    name.trim().length > 0 && selectedLabels.length >= minLabels;

  function toggleLabel(slug: string) {
    setSelectedLabels((cur) =>
      cur.includes(slug) ? cur.filter((s) => s !== slug) : [...cur, slug],
    );
  }
  function toggleRole(role: string) {
    setRoles((cur) =>
      cur.includes(role) ? cur.filter((r) => r !== role) : [...cur, role],
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New label policy</DialogTitle>
          <DialogDescription>
            Policies are evaluated against every search result. Drop hides the
            result; warn surfaces a banner; block also hides it.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-2">
            <FormLabel htmlFor="policy-name">Name</FormLabel>
            <Input
              id="policy-name"
              placeholder="No PII with public"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <FormLabel>Rule kind</FormLabel>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as RuleKind)}
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="mutually_exclusive">
                mutually_exclusive — labels can&apos;t co-exist
              </option>
              <option value="requires_role">
                requires_role — only certain roles see these labels
              </option>
            </select>
          </div>
          <div className="grid gap-2">
            <FormLabel>Labels in rule</FormLabel>
            <div className="flex flex-wrap gap-1.5">
              {labels.map((l) => {
                const active = selectedLabels.includes(l.slug);
                return (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => toggleLabel(l.slug)}
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      active
                        ? "border-foreground bg-foreground/10"
                        : "border-border"
                    }`}
                  >
                    {l.name}
                  </button>
                );
              })}
            </div>
          </div>
          {kind === "requires_role" && (
            <div className="grid gap-2">
              <FormLabel>Allowed roles</FormLabel>
              <div className="flex flex-wrap gap-1.5">
                {(["viewer", "editor", "admin", "owner"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => toggleRole(r)}
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      roles.includes(r)
                        ? "border-foreground bg-foreground/10"
                        : "border-border"
                    }`}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="grid gap-2">
            <FormLabel>Action when rule matches</FormLabel>
            <select
              value={action}
              onChange={(e) => setAction(e.target.value as LabelPolicyAction)}
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="drop">drop</option>
              <option value="warn">warn</option>
              <option value="block">block</option>
            </select>
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
