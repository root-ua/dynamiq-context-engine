"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  PiArrowsClockwise as Rotate,
  PiKey,
  PiPlus,
  PiTrash,
  PiWarningCircle,
} from "react-icons/pi";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CopyButton } from "@/components/ui/copy-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import {
  agentTokensApi,
  type AgentTokenCreated,
  type AgentTokenRow,
} from "@/lib/api/endpoints";
import { formatDate } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

type Client =
  | "claude-code"
  | "claude-desktop"
  | "cursor"
  | "claude-web"
  | "openai-sdk"
  | "curl";

const CLIENT_LABELS: Record<Client, string> = {
  "claude-code": "Claude Code",
  "claude-desktop": "Claude Desktop",
  cursor: "Cursor",
  "claude-web": "Claude Web",
  "openai-sdk": "OpenAI Agents SDK",
  curl: "curl",
};

function buildSnippet(client: Client, baseUrl: string, token: string): string {
  const tokenPlaceholder = token || "mem_paste_your_token_here";
  const url = `${baseUrl.replace(/\/$/, "")}/api/mcp/rpc`;
  switch (client) {
    case "claude-code":
      return `claude mcp add-json dynamiq '${JSON.stringify({
        type: "http",
        url,
        headers: { Authorization: `Bearer ${tokenPlaceholder}` },
      })}' --scope user`;
    case "claude-desktop":
      return JSON.stringify(
        {
          mcpServers: {
            dynamiq: {
              transport: "http",
              url,
              headers: { Authorization: `Bearer ${tokenPlaceholder}` },
            },
          },
        },
        null,
        2,
      );
    case "cursor":
      return JSON.stringify(
        {
          mcpServers: {
            dynamiq: {
              url,
              headers: { Authorization: `Bearer ${tokenPlaceholder}` },
            },
          },
        },
        null,
        2,
      );
    case "claude-web":
      return [
        "1. Open Claude web → Settings → Connectors → Add custom connector",
        `2. URL:  ${url}`,
        `3. Auth: Bearer  ${tokenPlaceholder}`,
        "4. Save. Claude will list the 22 Dynamiq tools.",
      ].join("\n");
    case "openai-sdk":
      return [
        "# pip install openai>=2.0",
        "from openai import OpenAI",
        "client = OpenAI()",
        "resp = client.responses.create(",
        '    model="gpt-5",',
        "    tools=[{",
        '        "type": "mcp",',
        '        "server_label": "dynamiq",',
        `        "server_url": "${url}",`,
        `        "headers": {"Authorization": "Bearer ${tokenPlaceholder}"},`,
        "    }],",
        '    input="What does our graph say about Acme?",',
        ")",
        "print(resp.output_text)",
      ].join("\n");
    case "curl":
      return [
        `curl -X POST '${url}' \\`,
        `  -H 'Authorization: Bearer ${tokenPlaceholder}' \\`,
        "  -H 'Content-Type: application/json' \\",
        '  -d \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\'',
      ].join("\n");
  }
}

export default function AgentsSettingsPage() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const { push } = useToast();
  const wsId = workspace?.id ?? "";

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<string>("");
  const [kind, setKind] = useState<"user" | "service">("service");
  const [justCreated, setJustCreated] = useState<AgentTokenCreated | null>(
    null,
  );
  const [activeClient, setActiveClient] = useState<Client>("claude-code");

  const apiOrigin = useMemo(() => {
    if (typeof window === "undefined") return "http://localhost:8000";
    const fromEnv = process.env.NEXT_PUBLIC_API_URL;
    return fromEnv || `${window.location.protocol}//${window.location.host}`;
  }, []);

  const tokens = useQuery({
    queryKey: ["agent-tokens", wsId],
    queryFn: () => agentTokensApi.list(wsId),
    enabled: !!wsId,
  });

  const createMut = useMutation({
    mutationFn: () =>
      agentTokensApi.create(wsId, {
        name: name.trim(),
        kind,
        expires_in_days: expiry ? Number(expiry) : undefined,
      }),
    onSuccess: (created) => {
      setJustCreated(created);
      setCreateOpen(false);
      setName("");
      setExpiry("");
      void qc.invalidateQueries({ queryKey: ["agent-tokens", wsId] });
    },
    onError: (err) => {
      push({
        variant: "destructive",
        title: "Could not create token",
        description: String(err),
      });
    },
  });

  const revokeMut = useMutation({
    mutationFn: (id: string) => agentTokensApi.revoke(wsId, id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent-tokens", wsId] });
      push({ title: "Token revoked" });
    },
  });

  const rotateMut = useMutation({
    mutationFn: (id: string) => agentTokensApi.rotate(wsId, id),
    onSuccess: (rotated) => {
      setJustCreated(rotated);
      void qc.invalidateQueries({ queryKey: ["agent-tokens", wsId] });
    },
  });

  const tokenForSnippet = justCreated?.token ?? "";

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">MCP agents</h1>
          <p className="text-sm text-muted-foreground">
            Mint tokens for Claude Code, Cursor, Claude Desktop, the Claude web
            app, or any other MCP-aware client to connect to this workspace.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <PiPlus className="size-4" />
          Create token
        </Button>
      </header>

      {/* Tokens table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Active tokens</CardTitle>
          <CardDescription>
            Tokens are workspace-scoped, argon2-hashed at rest, and never
            re-displayed after creation. Rotate immediately if a token leaks.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tokens.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (tokens.data ?? []).filter((t) => !t.revoked_at).length === 0 ? (
            <EmptyState
              icon={PiKey}
              title="No active tokens"
              description="Create your first MCP token to connect an external agent to this workspace."
              action={
                <Button onClick={() => setCreateOpen(true)}>
                  <PiPlus className="size-4" />
                  Create token
                </Button>
              }
            />
          ) : (
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-muted/30 text-left text-xs font-medium text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">Name</th>
                    <th className="px-3 py-2">Kind</th>
                    <th className="px-3 py-2">Prefix</th>
                    <th className="px-3 py-2">Last used</th>
                    <th className="px-3 py-2">Expires</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {(tokens.data ?? [])
                    .filter((t) => !t.revoked_at)
                    .map((t: AgentTokenRow) => (
                      <tr key={t.id} className="border-t">
                        <td className="px-3 py-2 font-medium">{t.name}</td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {t.kind}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">
                          mem_{t.prefix}…
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {t.last_used_at
                            ? formatDate(t.last_used_at)
                            : "Never"}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {t.expires_at ? formatDate(t.expires_at) : "—"}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => rotateMut.mutate(t.id)}
                            disabled={rotateMut.isPending}
                          >
                            <Rotate className="size-4" />
                            Rotate
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              if (
                                confirm(
                                  `Revoke "${t.name}"? Connected agents will lose access immediately.`,
                                )
                              )
                                revokeMut.mutate(t.id);
                            }}
                            disabled={revokeMut.isPending}
                          >
                            <PiTrash className="size-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Snippets */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Connect a client</CardTitle>
          <CardDescription>
            {justCreated
              ? "Your token is pre-filled into the snippets below. Copy and paste it into your client."
              : "Pick your client. Replace mem_paste_your_token_here with the token plaintext shown after you create one."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(CLIENT_LABELS) as Client[]).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setActiveClient(c)}
                className={
                  activeClient === c
                    ? "rounded-md bg-foreground px-3 py-1.5 text-xs text-background"
                    : "rounded-md border px-3 py-1.5 text-xs hover:bg-accent"
                }
              >
                {CLIENT_LABELS[c]}
              </button>
            ))}
          </div>

          <div className="relative rounded-lg border bg-muted/30">
            <pre className="overflow-x-auto p-4 text-xs leading-relaxed">
              <code>
                {buildSnippet(activeClient, apiOrigin, tokenForSnippet)}
              </code>
            </pre>
            <div className="absolute right-2 top-2">
              <CopyButton
                value={buildSnippet(activeClient, apiOrigin, tokenForSnippet)}
              />
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Note: ChatGPT&apos;s Custom GPTs use OpenAPI &ldquo;Actions&rdquo;,
            not MCP — use the OpenAI Agents SDK tab for an MCP-aware OpenAI
            flow. Anthropic&apos;s Claude clients (web, desktop, Code) all
            support this transport directly.
          </p>
        </CardContent>
      </Card>

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create MCP token</DialogTitle>
            <DialogDescription>
              The token plaintext is shown exactly once. Store it somewhere
              safe.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              createMut.mutate();
            }}
            className="space-y-3"
          >
            <div>
              <Label htmlFor="tok-name">Name</Label>
              <Input
                id="tok-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Alice's Claude Code"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="tok-kind">Kind</Label>
                <Select
                  id="tok-kind"
                  value={kind}
                  onChange={(e) =>
                    setKind(e.target.value as "user" | "service")
                  }
                >
                  <option value="service">Service (workspace-bound)</option>
                  <option value="user">User (acts as you)</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="tok-expiry">Expires in (days)</Label>
                <Input
                  id="tok-expiry"
                  type="number"
                  min={1}
                  max={3650}
                  value={expiry}
                  onChange={(e) => setExpiry(e.target.value)}
                  placeholder="optional"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMut.isPending}>
                {createMut.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Plaintext reveal */}
      <Dialog
        open={!!justCreated}
        onOpenChange={(o) => !o && setJustCreated(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Token created</DialogTitle>
            <DialogDescription className="flex items-start gap-2">
              <PiWarningCircle className="mt-0.5 size-4 shrink-0 text-amber-500" />
              <span>
                This is the only time you&apos;ll see this token. Copy it now
                and store it somewhere safe. You can always rotate or revoke it
                later.
              </span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="break-all rounded-md border bg-muted/30 p-3 font-mono text-xs">
              {justCreated?.token}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                Use the &ldquo;Connect a client&rdquo; section below — the
                snippets are pre-filled with this token.
              </span>
              <CopyButton value={justCreated?.token ?? ""} label="Copy token" />
            </div>
            <div className="flex justify-end pt-2">
              <Button onClick={() => setJustCreated(null)}>Done</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
