"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiArrowCounterClockwise as Restore,
  PiFloppyDisk as Save,
} from "react-icons/pi";

import { Button } from "@/components/ui/button";
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
import { useToast } from "@/components/ui/toast";
import { revisionsApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import type { DocumentRevision } from "@/lib/api/types";

interface Props {
  workspaceId: string;
  documentId: string;
}

export function RevisionPanel({ workspaceId, documentId }: Props) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [saveOpen, setSaveOpen] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [restoreTarget, setRestoreTarget] =
    React.useState<DocumentRevision | null>(null);

  const query = useQuery({
    queryKey: ["revisions", workspaceId, documentId],
    queryFn: () => revisionsApi.list(workspaceId, documentId),
    enabled: !!workspaceId && !!documentId,
  });

  const save = useMutation({
    mutationFn: () => revisionsApi.create(workspaceId, documentId, note),
    onSuccess: () => {
      push({ title: "Revision saved" });
      setSaveOpen(false);
      setNote("");
      void qc.invalidateQueries({
        queryKey: ["revisions", workspaceId, documentId],
      });
    },
    onError: (err) =>
      push({
        title: "Save failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const restore = useMutation({
    mutationFn: (rid: string) =>
      revisionsApi.restore(workspaceId, documentId, rid),
    onSuccess: () => {
      push({ title: "Restored" });
      setRestoreTarget(null);
      void qc.invalidateQueries({
        queryKey: ["revisions", workspaceId, documentId],
      });
      // Block tree changed — invalidate the editor's data.
      void qc.invalidateQueries({
        queryKey: ["documents", workspaceId, documentId],
      });
    },
    onError: (err) =>
      push({
        title: "Restore failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  const revisions = query.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Revisions</h2>
        <Button size="sm" variant="outline" onClick={() => setSaveOpen(true)}>
          <Save className="h-3.5 w-3.5" /> Save revision
        </Button>
      </div>

      {revisions.length === 0 ? (
        <EmptyState
          title="No revisions"
          description="Save a revision to checkpoint the current state."
        />
      ) : (
        <ul className="divide-y rounded-md border">
          {revisions.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between gap-2 p-2 text-sm"
            >
              <div className="min-w-0">
                <div className="font-mono text-xs text-muted-foreground">
                  {r.id.slice(0, 8)}
                </div>
                <div className="text-xs">
                  {formatDateTime(r.created_at)}
                  {r.note && (
                    <span className="ml-2 text-muted-foreground">
                      — {r.note}
                    </span>
                  )}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setRestoreTarget(r)}
                aria-label="Restore"
              >
                <Restore className="h-3.5 w-3.5" /> Restore
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save revision</DialogTitle>
            <DialogDescription>
              Captures the current block tree. Restorable via this panel.
            </DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Optional note (e.g. before refactor)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)}>
              Cancel
            </Button>
            <Button disabled={save.isPending} onClick={() => save.mutate()}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!restoreTarget}
        onOpenChange={(o) => {
          if (!o) setRestoreTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore revision?</DialogTitle>
            <DialogDescription>
              The current state will be saved as a fresh revision first, so you
              can undo this. Replaces the live block tree.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestoreTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={restore.isPending}
              onClick={() => {
                if (restoreTarget) restore.mutate(restoreTarget.id);
              }}
            >
              Restore
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
