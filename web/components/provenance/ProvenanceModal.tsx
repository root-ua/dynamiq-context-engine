"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { JsonView } from "@/components/ui/json-view";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { provenanceApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceId: string;
  edgeId: string;
}

interface ProvActivity {
  "@id"?: string;
  "@type"?: string;
  "dce:kind"?: string;
  startedAtTime?: string;
  endedAtTime?: string;
  wasAssociatedWith?: ProvAgent;
}

interface ProvAgent {
  "@id"?: string;
  "@type"?: string;
  "dce:agentKind"?: string;
  "dce:agentRef"?: string;
  "dce:agentVersion"?: string;
}

interface ProvEpisode {
  "@id"?: string;
  "@type"?: string[] | string;
  "dce:snippet"?: string;
  "dce:sourceKind"?: string;
  "dce:externalUrl"?: string;
}

interface ProvDoc {
  "@context"?: unknown;
  "@id"?: string;
  "@type"?: string[] | string;
  "dce:fact"?: string;
  "dce:confidence"?: number;
  wasGeneratedBy?: ProvActivity;
  wasDerivedFrom?: ProvEpisode;
  wasAttributedTo?: ProvAgent;
}

export function ProvenanceModal({
  open,
  onOpenChange,
  workspaceId,
  edgeId,
}: Props) {
  const query = useQuery({
    queryKey: ["provenance", "edge", workspaceId, edgeId],
    queryFn: () => provenanceApi.edge(workspaceId, edgeId),
    enabled: open && !!workspaceId && !!edgeId,
  });

  const doc = (query.data as ProvDoc | undefined) ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Provenance</DialogTitle>
          <DialogDescription>
            W3C PROV-O JSON-LD describing what produced this fact.
          </DialogDescription>
        </DialogHeader>

        {query.isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {query.isError && (
          <p className="text-sm text-destructive">
            {query.error instanceof Error
              ? query.error.message
              : "Failed to load provenance"}
          </p>
        )}

        {doc && (
          <div className="space-y-4 text-sm">
            {doc["dce:fact"] && (
              <div>
                <div className="text-xs uppercase text-muted-foreground">
                  Fact
                </div>
                <p className="text-foreground">{doc["dce:fact"]}</p>
                {typeof doc["dce:confidence"] === "number" && (
                  <p className="text-xs text-muted-foreground">
                    confidence {(doc["dce:confidence"] * 100).toFixed(0)}%
                  </p>
                )}
              </div>
            )}

            {doc.wasGeneratedBy && (
              <div>
                <div className="text-xs uppercase text-muted-foreground">
                  Activity
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">
                    {doc.wasGeneratedBy["dce:kind"] ?? "activity"}
                  </Badge>
                  {doc.wasGeneratedBy.startedAtTime && (
                    <span className="text-xs text-muted-foreground">
                      started {formatDateTime(doc.wasGeneratedBy.startedAtTime)}
                    </span>
                  )}
                </div>
                {doc.wasGeneratedBy.wasAssociatedWith && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    agent:{" "}
                    {doc.wasGeneratedBy.wasAssociatedWith["dce:agentKind"]} /{" "}
                    {doc.wasGeneratedBy.wasAssociatedWith["dce:agentRef"] ??
                      "unknown"}
                    {doc.wasGeneratedBy.wasAssociatedWith[
                      "dce:agentVersion"
                    ] && (
                      <>
                        {" "}
                        @
                        {
                          doc.wasGeneratedBy.wasAssociatedWith[
                            "dce:agentVersion"
                          ]
                        }
                      </>
                    )}
                  </p>
                )}
              </div>
            )}

            {doc.wasDerivedFrom && (
              <div>
                <div className="text-xs uppercase text-muted-foreground">
                  Source
                </div>
                {doc.wasDerivedFrom["dce:snippet"] && (
                  <p className="rounded-md border bg-muted/40 p-2 text-xs">
                    {doc.wasDerivedFrom["dce:snippet"]}
                    {doc.wasDerivedFrom["dce:snippet"].length === 200 && "…"}
                  </p>
                )}
                {doc.wasDerivedFrom["dce:externalUrl"] && (
                  <a
                    href={doc.wasDerivedFrom["dce:externalUrl"]}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-block text-xs underline"
                  >
                    open in source
                  </a>
                )}
              </div>
            )}

            <details className="rounded-md border bg-muted/30 p-2">
              <summary className="flex cursor-pointer items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>Raw JSON-LD</span>
                <CopyButton value={JSON.stringify(doc, null, 2)} label="" />
              </summary>
              <div className="mt-2 max-h-72 overflow-auto">
                <JsonView value={doc} />
              </div>
            </details>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
