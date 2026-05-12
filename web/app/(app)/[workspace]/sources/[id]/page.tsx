"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  PiArrowLeft as Back,
  PiArrowSquareOut as External,
  PiFile as File,
} from "react-icons/pi";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { sourcesApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function SourceDetailPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const detail = useQuery({
    queryKey: ["source", wsId, params.id],
    queryFn: () => sourcesApi.get(wsId, params.id),
    enabled: !!wsId && !!params.id,
  });

  if (detail.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  if (detail.isError || !detail.data) {
    return (
      <div className="space-y-4">
        <Button
          variant="outline"
          onClick={() => router.push(`/${wsSlug}/sources`)}
        >
          <Back className="h-4 w-4" />
          Back
        </Button>
        <p className="text-sm text-red-600">
          Source not found, or your identity does not grant access.
        </p>
      </div>
    );
  }

  const s = detail.data;

  return (
    <div className="space-y-6 max-w-4xl">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => router.push(`/${wsSlug}/sources`)}
      >
        <Back className="h-4 w-4" />
        All sources
      </Button>

      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <File className="h-5 w-5 text-muted-foreground" />
            {s.title}
          </h1>
          <p className="text-sm text-muted-foreground">
            {s.connector_kind} · external id {s.external_id}
            {s.last_modified_external && (
              <>
                {" · "}
                Modified {format(new Date(s.last_modified_external), "PP p")}
              </>
            )}
          </p>
        </div>
        {s.external_url && (
          <a
            href={s.external_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm inline-flex items-center gap-1 hover:underline"
          >
            Open in source
            <External className="h-3.5 w-3.5" />
          </a>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Derived facts</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {s.derived_edges.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No facts have been extracted from this document yet (extraction
              runs asynchronously after a crawl).
            </p>
          ) : (
            s.derived_edges.map((e) => (
              <div
                key={e.id}
                className="rounded-md border p-3 text-sm leading-relaxed"
              >
                <p>{e.fact}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {e.subject} <span className="opacity-50">·</span>{" "}
                  <span className="font-mono">{e.predicate}</span>{" "}
                  <span className="opacity-50">·</span> {e.object}
                </p>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {s.acl && Array.isArray(s.acl) && s.acl.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Source ACL</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="overflow-auto rounded-md bg-muted p-3 text-xs">
              {JSON.stringify(s.acl, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
