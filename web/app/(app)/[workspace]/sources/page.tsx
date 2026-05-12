"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PiFile as File, PiArrowSquareOut as External } from "react-icons/pi";
import { format } from "date-fns";

import { Card, CardContent } from "@/components/ui/card";
import { sourcesApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function SourcesPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";

  const list = useQuery({
    queryKey: ["sources", wsId],
    queryFn: () => sourcesApi.list(wsId, { limit: 100 }),
    enabled: !!wsId,
  });

  const items = list.data ?? [];

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-semibold">Source documents</h1>
        <p className="text-sm text-muted-foreground">
          Documents ingested by connectors. Only those you have access to in
          the source system are listed here.
        </p>
      </div>

      {list.isLoading && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      {!list.isLoading && items.length === 0 && (
        <Card>
          <CardContent className="p-12 text-center">
            <File className="mx-auto h-10 w-10 text-muted-foreground" />
            <p className="mt-3 text-base font-medium">No sources visible</p>
            <p className="mt-1 text-sm text-muted-foreground max-w-sm mx-auto">
              Either no connectors are installed yet, or you haven&apos;t linked
              your identity. Visit{" "}
              <Link
                href={`/${wsSlug}/settings/identity`}
                className="underline"
              >
                settings → identity
              </Link>{" "}
              to connect a Google account.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {items.map((s) => (
          <Card key={s.id}>
            <CardContent className="flex items-center justify-between gap-4 p-4">
              <div className="flex items-center gap-3 min-w-0">
                <File className="h-5 w-5 text-muted-foreground shrink-0" />
                <div className="min-w-0">
                  <Link
                    href={`/${wsSlug}/sources/${s.id}`}
                    className="font-medium hover:underline truncate"
                  >
                    {s.title}
                  </Link>
                  <div className="text-xs text-muted-foreground">
                    {s.connector_kind}
                    {s.last_modified_external && (
                      <>
                        {" · "}
                        Modified{" "}
                        {format(new Date(s.last_modified_external), "PP")}
                      </>
                    )}
                  </div>
                </div>
              </div>
              {s.external_url && (
                <a
                  href={s.external_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1"
                >
                  Open
                  <External className="h-3.5 w-3.5" />
                </a>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
