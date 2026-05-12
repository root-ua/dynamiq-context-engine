"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  PiCaretDown as ChevronDown,
  PiCaretRight as ChevronRight,
  PiFilePlus as FilePlus,
  PiArrowsClockwise as RefreshCcw,
} from "react-icons/pi";

import { ExtractionResults } from "@/components/episode/ExtractionResults";
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
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { episodesApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

export default function EpisodesPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const { push } = useToast();

  const [open, setOpen] = useState(false);
  const [sourceKind, setSourceKind] = useState("manual");
  const [sourceRef, setSourceRef] = useState("");
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const episodes = useQuery({
    queryKey: ["episodes", wsId],
    queryFn: () => episodesApi.list(wsId),
    enabled: !!wsId,
    refetchInterval: 5000,
  });

  async function ingest(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await episodesApi.create(wsId, {
        content,
        source_kind: sourceKind,
        source_ref: sourceRef || undefined,
        extract: true,
      });
      push({
        title: "Episode queued",
        description: "Extraction is running in the background.",
      });
      void qc.invalidateQueries({ queryKey: ["episodes", wsId] });
      setOpen(false);
      setContent("");
      setSourceRef("");
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

  async function reprocess(id: string) {
    try {
      await episodesApi.reprocess(wsId, id);
      push({ title: "Queued for reprocess" });
      void qc.invalidateQueries({ queryKey: ["episodes", wsId] });
    } catch (err: unknown) {
      push({
        title: "Failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  }

  if (!workspace) return null;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            Episodes
            {episodes.isFetching && (
              <span
                title="Polling for extraction updates"
                aria-label="Polling for extraction updates"
                className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand"
              />
            )}
          </h1>
          <p className="text-sm text-muted-foreground">
            Raw ingested content. An extraction job distills entities and facts
            from each episode. Auto-refreshing every 5s.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <FilePlus className="h-4 w-4" /> Ingest
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {(episodes.data ?? []).length === 0 ? (
            <div className="p-8">
              <EmptyState
                title="No episodes yet"
                description="Paste conversations, meeting notes, or emails. The extractor will propose entities and facts."
                action={
                  <Button onClick={() => setOpen(true)}>
                    <FilePlus className="h-4 w-4" /> Ingest your first
                  </Button>
                }
              />
            </div>
          ) : (
            <ul className="divide-y">
              {(episodes.data ?? []).map((e) => {
                const isOpen = !!expanded[e.id];
                const canExpand = e.processing_status === "completed";
                return (
                  <li key={e.id} className="space-y-2 p-4 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">{e.source_kind}</Badge>
                      <StatusBadge status={e.processing_status} />
                      {e.source_ref && (
                        <span className="text-xs text-muted-foreground">
                          {e.source_ref}
                        </span>
                      )}
                      <span className="ml-auto text-xs text-muted-foreground">
                        {formatDateTime(e.occurred_at)}
                      </span>
                    </div>
                    {e.content_text && (
                      <p className="line-clamp-3 text-muted-foreground">
                        {e.content_text}
                      </p>
                    )}
                    {e.processing_error && (
                      <p className="text-xs text-destructive">
                        {e.processing_error}
                      </p>
                    )}
                    {isOpen && workspace && (
                      <ExtractionResults
                        workspaceId={wsId}
                        workspaceSlug={workspace.slug}
                        episodeId={e.id}
                        enabled
                      />
                    )}
                    <div className="flex justify-end gap-2">
                      {canExpand && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setExpanded((prev) => ({
                              ...prev,
                              [e.id]: !prev[e.id],
                            }))
                          }
                        >
                          {isOpen ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                          )}
                          {isOpen ? "Hide" : "Show"} results
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => reprocess(e.id)}
                      >
                        <RefreshCcw className="h-3.5 w-3.5" /> Reprocess
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ingest an episode</DialogTitle>
            <DialogDescription>
              Paste any text. Extraction will produce entities + edges, and may
              extend the ontology if the workspace allows it.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={ingest} className="space-y-3">
            <div className="space-y-1">
              <Label>Source kind</Label>
              <Input
                value={sourceKind}
                onChange={(e) => setSourceKind(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label>Source reference (optional)</Label>
              <Input
                value={sourceRef}
                onChange={(e) => setSourceRef(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label>Content</Label>
              <Textarea
                required
                rows={10}
                value={content}
                onChange={(e) => setContent(e.target.value)}
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
              <Button type="submit" disabled={submitting || content.length < 3}>
                {submitting ? "Queuing…" : "Ingest"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "completed"
      ? "default"
      : status === "failed"
        ? "destructive"
        : "secondary";
  return <Badge variant={variant}>{status}</Badge>;
}
