"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  PiCheck as Check,
  PiX as X,
  PiArrowsClockwise as RefreshCcw,
} from "react-icons/pi";

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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { proposalsApi, proposalsBulkApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import type { PendingFact } from "@/lib/api/types";
import { useWorkspace } from "@/lib/workspace-context";

type Status = "pending" | "approved" | "rejected";

const STATUS_LABEL: Record<Status, string> = {
  pending: "Pending review",
  approved: "Approved",
  rejected: "Rejected",
};

export default function ReviewQueuePage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const { push } = useToast();
  const [status, setStatus] = useState<Status>("pending");
  const [rejecting, setRejecting] = useState<PendingFact | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [bulkRejectOpen, setBulkRejectOpen] = useState(false);
  const [bulkRejectReason, setBulkRejectReason] = useState("");

  const proposals = useQuery({
    queryKey: ["proposals", wsId, status],
    queryFn: () => proposalsApi.list(wsId, { status, limit: 100 }),
    enabled: !!wsId,
    refetchInterval: 5_000,
  });

  const approve = useMutation({
    mutationFn: (id: string) => proposalsApi.approve(wsId, id),
    onSuccess: (data) => {
      push({
        title: "Approved",
        description: `Promoted to edge ${data.approved_edge_id.slice(0, 8)}.`,
      });
      void qc.invalidateQueries({ queryKey: ["proposals", wsId] });
    },
    onError: (err) =>
      push({
        title: "Failed to approve",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const reject = useMutation({
    mutationFn: (args: { id: string; reason: string }) =>
      proposalsApi.reject(wsId, args.id, args.reason),
    onSuccess: () => {
      push({ title: "Rejected" });
      setRejecting(null);
      setRejectReason("");
      void qc.invalidateQueries({ queryKey: ["proposals", wsId] });
    },
    onError: (err) =>
      push({
        title: "Failed to reject",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const rows = proposals.data ?? [];

  const bulkApprove = useMutation({
    mutationFn: (ids: string[]) =>
      proposalsBulkApi.approve(wsId, { ids, comment: null }),
    onSuccess: ({ results }) => {
      const ok = results.filter((r) => r.ok).length;
      const fail = results.length - ok;
      push({
        title: `Approved ${ok} / ${results.length}`,
        description: fail ? `${fail} failed; see console.` : undefined,
      });
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ["proposals", wsId] });
    },
    onError: (err) =>
      push({
        title: "Bulk approve failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const bulkReject = useMutation({
    mutationFn: (args: { ids: string[]; reason: string }) =>
      proposalsBulkApi.reject(wsId, args),
    onSuccess: ({ results }) => {
      const ok = results.filter((r) => r.ok).length;
      push({ title: `Rejected ${ok} / ${results.length}` });
      setSelected(new Set());
      setBulkRejectOpen(false);
      setBulkRejectReason("");
      void qc.invalidateQueries({ queryKey: ["proposals", wsId] });
    },
    onError: (err) =>
      push({
        title: "Bulk reject failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  function toggle(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAll() {
    if (status !== "pending") return;
    if (selected.size === rows.length) setSelected(new Set());
    else setSelected(new Set(rows.map((r) => r.id)));
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Review queue</h1>
          <p className="text-sm text-muted-foreground">
            Low-confidence extractions that need human approval before they
            become live facts.
          </p>
        </div>
        <div className="flex gap-2">
          {(["pending", "approved", "rejected"] as Status[]).map((s) => (
            <Button
              key={s}
              size="sm"
              variant={status === s ? "default" : "outline"}
              onClick={() => setStatus(s)}
            >
              {STATUS_LABEL[s]}
            </Button>
          ))}
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              qc.invalidateQueries({ queryKey: ["proposals", wsId] })
            }
            aria-label="Refresh"
          >
            <RefreshCcw className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {rows.length === 0 ? (
        <EmptyState
          title="Nothing to review"
          description={
            status === "pending"
              ? "No facts are currently waiting for approval. As extraction runs, low-confidence facts will appear here."
              : `No ${status} facts in this workspace yet.`
          }
        />
      ) : (
        <>
          {status === "pending" && (
            <div className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2 text-xs">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={rows.length > 0 && selected.size === rows.length}
                  onChange={toggleAll}
                />
                Select all on page
              </label>
              <span className="text-muted-foreground">
                {selected.size} selected
              </span>
            </div>
          )}
          <div className="space-y-3">
            {rows.map((p) => (
              <ProposalRow
                key={p.id}
                proposal={p}
                selected={selected.has(p.id)}
                onToggle={() => toggle(p.id)}
                onApprove={() => approve.mutate(p.id)}
                onReject={() => {
                  setRejecting(p);
                  setRejectReason("");
                }}
                busy={approve.isPending || reject.isPending}
                selectable={status === "pending"}
              />
            ))}
          </div>
        </>
      )}

      {status === "pending" && selected.size > 0 && (
        <div className="sticky bottom-4 flex items-center justify-between gap-3 rounded-lg border bg-background/95 p-3 shadow-lg backdrop-blur">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={bulkReject.isPending}
              onClick={() => setBulkRejectOpen(true)}
            >
              <X className="mr-1 h-4 w-4" />
              Reject {selected.size}
            </Button>
            <Button
              size="sm"
              disabled={bulkApprove.isPending}
              onClick={() => bulkApprove.mutate(Array.from(selected))}
            >
              <Check className="mr-1 h-4 w-4" />
              Approve {selected.size}
            </Button>
          </div>
        </div>
      )}

      <Dialog
        open={bulkRejectOpen}
        onOpenChange={(open) => {
          if (!open) {
            setBulkRejectOpen(false);
            setBulkRejectReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject {selected.size} proposals</DialogTitle>
            <DialogDescription>
              The same reason will be recorded on each rejection.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="bulk-reject-reason">Reason</Label>
            <Textarea
              id="bulk-reject-reason"
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              rows={4}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setBulkRejectOpen(false);
                setBulkRejectReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={!bulkRejectReason.trim() || bulkReject.isPending}
              onClick={() =>
                bulkReject.mutate({
                  ids: Array.from(selected),
                  reason: bulkRejectReason.trim(),
                })
              }
            >
              Reject {selected.size}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!rejecting}
        onOpenChange={(open) => {
          if (!open) {
            setRejecting(null);
            setRejectReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject proposal</DialogTitle>
            <DialogDescription>
              The fact stays in the audit trail with your reason attached. No
              edge is created.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reject-reason">Reason</Label>
            <Textarea
              id="reject-reason"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="e.g. The extractor misread the date as 'last Tuesday' for an event from 2023."
              rows={4}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRejecting(null);
                setRejectReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={!rejectReason.trim() || reject.isPending}
              onClick={() => {
                if (rejecting) {
                  reject.mutate({
                    id: rejecting.id,
                    reason: rejectReason.trim(),
                  });
                }
              }}
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProposalRow({
  proposal,
  onApprove,
  onReject,
  busy,
  selected,
  onToggle,
  selectable,
}: {
  proposal: PendingFact;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
  selected: boolean;
  onToggle: () => void;
  selectable: boolean;
}) {
  const conf = Math.round(proposal.confidence * 100);
  const confTone =
    proposal.confidence >= 0.5
      ? "default"
      : proposal.confidence >= 0.3
        ? "secondary"
        : "destructive";
  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-4">
        {selectable && (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            className="mt-1 h-4 w-4 shrink-0"
            aria-label="Select proposal"
          />
        )}
        <div className="min-w-0 flex-1">
          <p className="break-words font-medium">{proposal.fact}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant={confTone}>{conf}% confidence</Badge>
            {proposal.source_kind && (
              <Badge variant="outline">{proposal.source_kind}</Badge>
            )}
            {proposal.reason && (
              <span className="italic">reason: {proposal.reason}</span>
            )}
            <span>·</span>
            <span>{formatDateTime(proposal.created_at)}</span>
            {proposal.reviewed_at && (
              <>
                <span>·</span>
                <span>reviewed {formatDateTime(proposal.reviewed_at)}</span>
              </>
            )}
          </div>
        </div>
        {proposal.status === "pending" && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={onReject}
              aria-label="Reject"
            >
              <X className="mr-1 h-4 w-4" /> Reject
            </Button>
            <Button
              size="sm"
              disabled={busy}
              onClick={onApprove}
              aria-label="Approve"
            >
              <Check className="mr-1 h-4 w-4" /> Approve
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
