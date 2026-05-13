"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { PiLightning as Lightning } from "react-icons/pi";

import { ActionInvocationForm } from "@/components/actions/ActionInvocationForm";
import { InvocationStatusBadge } from "@/components/actions/InvocationStatusBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { actionTypesApi, actionsApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import type { ActionType } from "@/lib/api/types";
import { useWorkspace } from "@/lib/workspace-context";

export default function ActionsPage() {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? "";

  const typesQuery = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionTypesApi.list(workspaceId),
    enabled: !!workspaceId,
  });
  const invocationsQuery = useQuery({
    queryKey: ["action-invocations", workspaceId],
    queryFn: () => actionsApi.listInvocations(workspaceId, { limit: 50 }),
    enabled: !!workspaceId,
    refetchInterval: 5000,
  });

  const types = React.useMemo(() => typesQuery.data ?? [], [typesQuery.data]);
  const invocations = invocationsQuery.data ?? [];
  const [selected, setSelected] = React.useState<ActionType | null>(null);

  React.useEffect(() => {
    if (!selected && types.length > 0) {
      setSelected(types[0] ?? null);
    }
  }, [types, selected]);

  if (!workspace) {
    return (
      <main className="mx-auto max-w-5xl p-8">
        <EmptyState
          icon={Lightning}
          title="No workspace"
          description="Select or create a workspace to use kinetic actions."
        />
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-full min-h-[calc(100vh-6rem)] max-w-7xl flex-col gap-6 p-4 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Actions</h1>
        <p className="text-sm text-muted-foreground">
          Registered kinetic actions for this workspace. Invocations are
          idempotent on their key.
        </p>
      </header>

      <Tabs defaultValue="catalog" className="flex min-h-0 flex-1 flex-col">
        <TabsList>
          <TabsTrigger value="catalog">
            Catalog
            <span className="ml-2 rounded-full bg-muted-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
              {types.length}
            </span>
          </TabsTrigger>
          <TabsTrigger value="history">
            History
            <span className="ml-2 rounded-full bg-muted-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
              {invocations.length}
            </span>
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="catalog"
          className="mt-4 grid min-h-0 flex-1 gap-4 md:grid-cols-[320px_minmax(0,1fr)]"
        >
          <Card className="flex min-h-0 flex-col overflow-hidden">
            <div className="border-b p-3 text-sm font-semibold">
              Action types
            </div>
            {types.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No action types registered yet.
              </p>
            ) : (
              <ul className="divide-y overflow-auto">
                {types.map((t) => {
                  const active = selected?.id === t.id;
                  return (
                    <li key={t.id}>
                      <button
                        type="button"
                        onClick={() => setSelected(t)}
                        className={`block w-full px-3 py-2 text-left text-sm transition ${
                          active ? "bg-muted font-medium" : "hover:bg-muted/50"
                        }`}
                      >
                        <div>{t.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {t.slug}
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          <div className="min-h-0">
            {selected ? (
              <ActionInvocationForm
                workspaceId={workspaceId}
                actionType={selected}
              />
            ) : (
              <EmptyState
                icon={Lightning}
                title="Pick an action"
                description="Choose an action type from the list to invoke it."
              />
            )}
          </div>
        </TabsContent>

        <TabsContent
          value="history"
          className="mt-4 flex min-h-0 flex-1 flex-col gap-3"
        >
          {invocations.length === 0 ? (
            <EmptyState
              title="No invocations yet"
              description="Action invocations will appear here once the catalog is in use."
            />
          ) : (
            <div className="space-y-2">
              {invocations.map((inv) => (
                <Card key={inv.id}>
                  <CardHeader className="space-y-1 p-3 pb-2">
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle className="text-sm">
                        {inv.action_type_slug}
                      </CardTitle>
                      <InvocationStatusBadge status={inv.status} />
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>{formatDateTime(inv.started_at)}</span>
                      <Badge variant="outline" className="font-mono">
                        {inv.idempotency_key.slice(0, 8)}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="p-3 pt-0">
                    {inv.error_message ? (
                      <p className="text-xs text-destructive">
                        {inv.error_message}
                      </p>
                    ) : (
                      inv.result && (
                        <pre className="overflow-x-auto rounded bg-muted/40 p-2 text-[11px] leading-tight">
                          {JSON.stringify(inv.result, null, 2)}
                        </pre>
                      )
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </main>
  );
}
