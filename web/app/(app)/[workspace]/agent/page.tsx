"use client";

import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import type { IChangeEvent } from "@rjsf/core";
import type { RegistryWidgetsType } from "@rjsf/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  PiCpu as Cpu,
  PiPlay as Play,
  PiTerminal as Terminal,
} from "react-icons/pi";

import { EntityRefWidget } from "@/components/agent/EntityRefWidget";
import { EntityTypeRefWidget } from "@/components/agent/EntityTypeRefWidget";
import { RelationRefWidget } from "@/components/agent/RelationRefWidget";
import { uiSchemaForTool } from "@/components/agent/tool-ui-schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { JsonView } from "@/components/ui/json-view";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { mcpApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

const WIDGETS: RegistryWidgetsType = {
  entityRef: EntityRefWidget,
  entityTypeRef: EntityTypeRefWidget,
  relationRef: RelationRefWidget,
};

export default function AgentConsolePage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const { push } = useToast();

  const tools = useQuery({
    queryKey: ["mcp-tools", wsId],
    queryFn: () => mcpApi.tools(wsId),
    enabled: !!wsId,
  });
  const sessions = useQuery({
    queryKey: ["agent-sessions", wsId],
    queryFn: () => mcpApi.sessions(wsId),
    enabled: !!wsId,
  });

  const [selected, setSelected] = useState<string | null>(null);
  const [args, setArgs] = useState<Record<string, unknown>>({});
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(
    null,
  );
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const activeTool = tools.data?.tools.find((t) => t.name === selected) ?? null;

  async function invoke() {
    if (!activeTool || !workspace) return;
    setRunning(true);
    try {
      const res = await mcpApi.invoke(wsId, {
        name: activeTool.name,
        arguments: args,
        session_id: sessionId ?? undefined,
      });
      setLastResult(res.result);
      setSessionId(res.session_id);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", wsId] });
      if (sessionId)
        void qc.invalidateQueries({
          queryKey: ["session-calls", wsId, sessionId],
        });
    } catch (err: unknown) {
      push({
        title: "Invocation failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setRunning(false);
    }
  }

  if (!workspace) return null;

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 md:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Agent console
          </h1>
          <p className="text-sm text-muted-foreground">
            Invoke MCP tools manually. External agents (Claude Desktop, Cursor,
            custom) can connect to{" "}
            <code className="rounded bg-muted px-1 py-0.5">/api/mcp/rpc</code>{" "}
            with a bearer token.
          </p>
        </div>
        <Card className="p-3 text-xs">
          <div className="font-medium">Endpoint</div>
          <code className="text-muted-foreground">POST /api/mcp/rpc</code>
          <div className="mt-1 font-medium">Workspace</div>
          <div className="text-muted-foreground">
            {workspace.slug} · {workspace.id}
          </div>
        </Card>
      </div>

      <Tabs defaultValue="invoke">
        <TabsList>
          <TabsTrigger value="invoke">Invoke</TabsTrigger>
          <TabsTrigger value="sessions">Sessions</TabsTrigger>
        </TabsList>

        <TabsContent value="invoke">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
            <Card className="self-start">
              <CardHeader>
                <CardTitle className="text-base">Available tools</CardTitle>
                <CardDescription>
                  {tools.data?.tools.length ?? 0} tools in the registry
                </CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <ul className="divide-y">
                  {(tools.data?.tools ?? []).map((t) => (
                    <li key={t.name}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelected(t.name);
                          setArgs({});
                          setLastResult(null);
                        }}
                        className={
                          "relative flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent/60 " +
                          (selected === t.name
                            ? "bg-accent text-accent-foreground before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-full before:bg-brand"
                            : "")
                        }
                      >
                        <Terminal className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <div className="font-mono text-xs font-medium">
                            {t.name}
                          </div>
                          <div className="line-clamp-2 text-xs text-muted-foreground">
                            {t.description}
                          </div>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            <div className="space-y-3">
              {activeTool ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="font-mono text-sm">
                      {activeTool.name}
                    </CardTitle>
                    <CardDescription>{activeTool.description}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <Form
                      schema={activeTool.input_schema}
                      validator={validator}
                      formData={args}
                      onChange={(e: IChangeEvent) =>
                        setArgs(e.formData as Record<string, unknown>)
                      }
                      widgets={WIDGETS}
                      uiSchema={uiSchemaForTool(activeTool.name)}
                    />
                    <div className="flex justify-end">
                      <Button onClick={invoke} disabled={running}>
                        <Play className="h-4 w-4" />{" "}
                        {running ? "Running…" : "Invoke"}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ) : (
                <EmptyState
                  icon={Cpu}
                  title="Pick a tool"
                  description="Select a tool from the catalog to see its schema and invoke it."
                />
              )}

              {lastResult && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Result</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-96 overflow-auto">
                      <JsonView value={lastResult} />
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="sessions">
          <SessionsTab
            wsId={wsId}
            sessions={sessions.data ?? []}
            activeSessionId={sessionId}
            setActive={setSessionId}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SessionsTab({
  wsId,
  sessions,
  activeSessionId,
  setActive,
}: {
  wsId: string;
  sessions: Array<{
    id: string;
    client: string;
    started_at: string;
    tool_calls: number;
  }>;
  activeSessionId: string | null;
  setActive: (id: string) => void;
}) {
  const calls = useQuery({
    queryKey: ["session-calls", wsId, activeSessionId],
    queryFn: () =>
      activeSessionId
        ? mcpApi.sessionCalls(wsId, activeSessionId)
        : Promise.resolve([]),
    enabled: !!activeSessionId,
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Agent sessions</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {sessions.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">
              No sessions yet.
            </div>
          ) : (
            <ul className="divide-y">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setActive(s.id)}
                    className={
                      "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-accent " +
                      (activeSessionId === s.id ? "bg-accent" : "")
                    }
                  >
                    <div className="min-w-0">
                      <div className="font-mono text-xs">
                        {s.id.slice(0, 8)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {s.client || "unknown"} · {formatDateTime(s.started_at)}
                      </div>
                    </div>
                    <Badge variant="secondary">{s.tool_calls}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tool calls</CardTitle>
          <CardDescription>
            {activeSessionId
              ? `Session ${activeSessionId.slice(0, 8)}`
              : "Select a session"}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {!activeSessionId ? (
            <div className="p-4 text-sm text-muted-foreground">
              Pick a session on the left.
            </div>
          ) : (calls.data ?? []).length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">
              No calls in this session.
            </div>
          ) : (
            <ul className="divide-y">
              {(calls.data ?? []).map((c) => (
                <li key={c.id} className="p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <code className="rounded bg-muted px-1 text-xs">
                      {c.tool}
                    </code>
                    <Badge variant="outline">{c.latency_ms} ms</Badge>
                    {c.error && <Badge variant="destructive">error</Badge>}
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(c.created_at)}
                    </span>
                  </div>
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-muted-foreground">
                      input / output
                    </summary>
                    <div className="mt-2 grid gap-2 text-xs lg:grid-cols-2">
                      <JsonView value={c.input} />
                      {c.error ? (
                        <pre className="overflow-auto rounded bg-muted p-2 text-destructive">
                          {c.error}
                        </pre>
                      ) : (
                        <JsonView value={c.output} />
                      )}
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
