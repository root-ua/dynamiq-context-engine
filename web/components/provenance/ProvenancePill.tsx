"use client";

import * as React from "react";

import { ProvenanceModal } from "@/components/provenance/ProvenanceModal";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";

interface Props {
  workspaceId: string;
  edgeId: string;
  createdAt?: string | null;
  /** Optional short label override (e.g. ``"extracted by Claude"``). */
  label?: string;
}

/**
 * Inline pill on an edge row that opens a full PROV-O JSON-LD modal on
 * click. Lazy: the modal fetches the doc only when opened.
 */
export function ProvenancePill({
  workspaceId,
  edgeId,
  createdAt,
  label,
}: Props) {
  const [open, setOpen] = React.useState(false);
  const date = createdAt ? formatDateTime(createdAt) : null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center"
        aria-label="View provenance"
      >
        <Badge
          variant="outline"
          className="cursor-pointer text-[10px] font-normal text-muted-foreground hover:bg-muted"
        >
          {label ?? "provenance"}
          {date ? ` · ${date}` : ""}
        </Badge>
      </button>
      <ProvenanceModal
        open={open}
        onOpenChange={setOpen}
        workspaceId={workspaceId}
        edgeId={edgeId}
      />
    </>
  );
}
