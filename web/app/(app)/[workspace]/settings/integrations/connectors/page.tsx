"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiPlugs as Plug,
  PiPlus as Plus,
  PiArrowsClockwise as Refresh,
  PiTrash as Trash,
} from "react-icons/pi";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import {
  connectorsApi,
  type ConnectorInstance,
} from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

const STATUS_LABEL: Record<ConnectorInstance["status"], string> = {
  inactive: "Inactive",
  authorizing: "Awaiting OAuth",
  active: "Active",
  paused: "Paused",
  error: "Error",
};

function StatusBadge({ status }: { status: ConnectorInstance["status"] }) {
  const tone =
    status === "active"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : status === "error"
        ? "bg-red-50 text-red-700 ring-red-200"
        : status === "authorizing"
          ? "bg-amber-50 text-amber-700 ring-amber-200"
          : "bg-zinc-50 text-zinc-700 ring-zinc-200";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export default function ConnectorsListPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";
  const router = useRouter();
  const qc = useQueryClient();
  const { push } = useToast();

  const list = useQuery({
    queryKey: ["connectors", wsId],
    queryFn: () => connectorsApi.list(wsId),
    enabled: !!wsId,
    refetchInterval: (q) => {
      const data = q.state.data;
      const anyTransitional = data?.some(
        (c) => c.status === "authorizing" || c.status === "active",
      );
      return anyTransitional ? 5000 : false;
    },
  });

  const resync = useMutation({
    mutationFn: (id: string) => connectorsApi.resync(wsId, id),
    onSuccess: () => {
      push({ title: "Re-crawl scheduled" });
      void qc.invalidateQueries({ queryKey: ["connectors", wsId] });
    },
    onError: (e: Error) =>
      push({
        title: "Resync failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => connectorsApi.remove(wsId, id),
    onSuccess: () => {
      push({ title: "Connector disconnected" });
      void qc.invalidateQueries({ queryKey: ["connectors", wsId] });
    },
    onError: (e: Error) =>
      push({
        title: "Disconnect failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const items = list.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Connectors</h1>
          <p className="text-sm text-muted-foreground">
            Pull facts from external sources. Each fact inherits the source
            document's access permissions.
          </p>
        </div>
        <Button onClick={() => router.push(`/${wsSlug}/settings/integrations/connectors/new`)}>
          <Plus className="h-4 w-4" />
          Add connector
        </Button>
      </div>

      {list.isLoading && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      {!list.isLoading && items.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-12 text-center">
            <Plug className="h-10 w-10 text-muted-foreground" />
            <p className="text-base font-medium">No connectors yet</p>
            <p className="text-sm text-muted-foreground max-w-sm">
              Add Google Drive to start ingesting documents. Facts derived from
              each document inherit its source-system ACL automatically.
            </p>
            <Button
              variant="outline"
              onClick={() =>
                router.push(`/${wsSlug}/settings/integrations/connectors/new`)
              }
            >
              <Plus className="h-4 w-4" />
              Add Google Drive
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {items.map((c) => (
          <Card key={c.id}>
            <CardContent className="flex items-center justify-between gap-4 p-4">
              <div className="flex items-center gap-3 min-w-0">
                <Plug className="h-5 w-5 text-muted-foreground shrink-0" />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/${wsSlug}/settings/integrations/connectors/${c.id}`}
                      className="font-medium hover:underline truncate"
                    >
                      {c.display_name}
                    </Link>
                    <StatusBadge status={c.status} />
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {c.connector_kind} ·{" "}
                    {c.last_full_crawl_at
                      ? `Last full crawl ${format(new Date(c.last_full_crawl_at), "PP p")}`
                      : "Never crawled"}
                    {c.last_error && (
                      <span className="ml-2 text-red-600">
                        · {c.last_error}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={c.status === "authorizing" || resync.isPending}
                  onClick={() => resync.mutate(c.id)}
                >
                  <Refresh className="h-3.5 w-3.5" />
                  Resync
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (
                      window.confirm(
                        `Disconnect "${c.display_name}"? Existing source documents will be hidden but not deleted.`,
                      )
                    ) {
                      remove.mutate(c.id);
                    }
                  }}
                >
                  <Trash className="h-3.5 w-3.5" />
                  Disconnect
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
