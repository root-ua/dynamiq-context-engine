"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Select } from "@/components/ui/select";
import { auditApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

type Filter = "all" | "user" | "agent" | "system";

export default function ActivityPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";

  const [filter, setFilter] = useState<Filter>("all");

  const audit = useQuery({
    queryKey: ["audit", wsId],
    queryFn: () => auditApi.list(wsId, 200),
    enabled: !!wsId,
  });

  const rows = useMemo(
    () =>
      (audit.data ?? []).filter(
        (a) => filter === "all" || a.actor_kind === filter,
      ),
    [audit.data, filter],
  );

  if (!workspace) return null;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <p className="text-sm text-muted-foreground">
          Every human and agent action in this workspace, with provenance.
        </p>
      </header>

      <Card>
        <CardHeader className="flex-row items-center gap-3">
          <CardTitle className="flex-1 text-base">Actor</CardTitle>
          <Select
            value={filter}
            onChange={(e) => setFilter(e.target.value as Filter)}
            className="w-40"
          >
            <option value="all">All actors</option>
            <option value="user">Users</option>
            <option value="agent">Agents</option>
            <option value="system">System</option>
          </Select>
        </CardHeader>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <div className="p-6">
              <EmptyState title="No activity yet" />
            </div>
          ) : (
            <ul className="divide-y text-sm">
              {rows.map((a) => (
                <li
                  key={a.id}
                  className="flex items-start justify-between gap-3 px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      variant={
                        a.actor_kind === "agent"
                          ? "secondary"
                          : a.actor_kind === "system"
                            ? "outline"
                            : "default"
                      }
                    >
                      {a.actor_kind}
                    </Badge>
                    <code className="rounded bg-muted px-1 py-0.5 text-xs">
                      {a.action}
                    </code>
                    <span className="text-xs text-muted-foreground">
                      on {a.target_kind}
                      {a.target_id ? ` · ${a.target_id.slice(0, 8)}` : ""}
                    </span>
                    {a.diff && Object.keys(a.diff).length > 0 && (
                      <details className="w-full">
                        <summary className="cursor-pointer text-xs text-muted-foreground">
                          diff
                        </summary>
                        <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted p-2 text-xs">
                          {JSON.stringify(a.diff, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatDateTime(a.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
