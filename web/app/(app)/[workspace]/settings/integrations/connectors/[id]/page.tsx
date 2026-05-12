"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiArrowLeft as Back,
  PiArrowsClockwise as Refresh,
  PiTrash as Trash,
} from "react-icons/pi";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { connectorsApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function ConnectorDetailPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = params.id;
  const qc = useQueryClient();
  const { push } = useToast();

  const detail = useQuery({
    queryKey: ["connector", wsId, id],
    queryFn: () => connectorsApi.get(wsId, id),
    enabled: !!wsId && !!id,
    refetchInterval: (q) => {
      const data = q.state.data;
      return data && (data.status === "authorizing" || data.status === "active")
        ? 5000
        : false;
    },
  });

  const resync = useMutation({
    mutationFn: () => connectorsApi.resync(wsId, id),
    onSuccess: () => {
      push({ title: "Re-crawl scheduled" });
      void qc.invalidateQueries({ queryKey: ["connector", wsId, id] });
    },
    onError: (e: Error) =>
      push({
        title: "Resync failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const remove = useMutation({
    mutationFn: () => connectorsApi.remove(wsId, id),
    onSuccess: () => {
      push({ title: "Connector disconnected" });
      router.push(`/${wsSlug}/settings/integrations/connectors`);
    },
    onError: (e: Error) =>
      push({
        title: "Disconnect failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  if (detail.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  if (detail.isError || !detail.data) {
    return (
      <div className="space-y-4">
        <Button
          variant="outline"
          onClick={() =>
            router.push(`/${wsSlug}/settings/integrations/connectors`)
          }
        >
          <Back className="h-4 w-4" />
          Back
        </Button>
        <p className="text-sm text-red-600">Connector not found.</p>
      </div>
    );
  }

  const c = detail.data;

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              router.push(`/${wsSlug}/settings/integrations/connectors`)
            }
          >
            <Back className="h-4 w-4" />
            All connectors
          </Button>
          <h1 className="text-2xl font-semibold mt-2">{c.display_name}</h1>
          <p className="text-sm text-muted-foreground">
            {c.connector_kind} · status{" "}
            <span className="font-medium">{c.status}</span>
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={c.status === "authorizing" || resync.isPending}
            onClick={() => resync.mutate()}
          >
            <Refresh className="h-4 w-4" />
            Resync
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              if (
                window.confirm(
                  `Disconnect "${c.display_name}"? Existing source documents will be hidden.`,
                )
              ) {
                remove.mutate();
              }
            }}
          >
            <Trash className="h-4 w-4" />
            Disconnect
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Crawl history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Last full crawl</span>
            <span>
              {c.last_full_crawl_at
                ? format(new Date(c.last_full_crawl_at), "PP p")
                : "Never"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Last incremental</span>
            <span>
              {c.last_incremental_at
                ? format(new Date(c.last_incremental_at), "PP p")
                : "Never"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Credentials</span>
            <span>{c.has_credentials ? "Stored" : "Missing"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Created</span>
            <span>{format(new Date(c.created_at), "PP p")}</span>
          </div>
        </CardContent>
      </Card>

      {c.last_error && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base text-red-700">
              Last error
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-xs text-red-700">
              {c.last_error}
            </pre>
          </CardContent>
        </Card>
      )}

      {c.status === "authorizing" && (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Waiting for OAuth completion. If you closed the consent window,
            disconnect this connector and add it again.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
