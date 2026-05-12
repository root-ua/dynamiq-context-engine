"use client";

import * as React from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiCopy as Copy,
  PiCpu as Cpu,
  PiKey as Key,
  PiPlugs as Plug,
  PiPlus as Plus,
  PiTrash as Trash,
  PiUser as User,
  PiWarning as Warning,
} from "react-icons/pi";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import {
  agentTokensApi,
  type AgentTokenCreated,
  type AgentTokenRow,
} from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

const MCP_PATH = "/api/mcp/rpc";

function mcpUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return base.replace(/\/$/, "") + MCP_PATH;
}

function CopyButton({ value, label }: { value: string; label?: string }) {
  const { push } = useToast();
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => {
        void navigator.clipboard.writeText(value);
        push({ title: `${label ?? "Copied"} to clipboard` });
      }}
    >
      <Copy className="h-3.5 w-3.5" /> Copy
    </Button>
  );
}

export default function IntegrationsPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const { push } = useToast();

  const tokens = useQuery({
    queryKey: ["agent-tokens", wsId],
    queryFn: () => agentTokensApi.list(wsId),
    enabled: !!wsId,
  });

  const [createOpen, setCreateOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [expiry, setExpiry] = React.useState<"never" | "30" | "90" | "365">(
    "never",
  );
  const [justCreated, setJustCreated] =
    React.useState<AgentTokenCreated | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      agentTokensApi.create(wsId, {
        name,
        expires_in_days: expiry === "never" ? null : Number(expiry),
      }),
    onSuccess: (created) => {
      setJustCreated(created);
      setName("");
      setExpiry("never");
      setCreateOpen(false);
      void qc.invalidateQueries({ queryKey: ["agent-tokens", wsId] });
    },
    onError: (e: Error) =>
      push({
        title: "Create failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => agentTokensApi.revoke(wsId, id),
    onSuccess: () => {
      push({ title: "Token revoked" });
      void qc.invalidateQueries({ queryKey: ["agent-tokens", wsId] });
    },
    onError: (e: Error) =>
      push({
        title: "Revoke failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  if (!workspace) return null;

  const url = mcpUrl();
  const tokenForSnippets = justCreated?.token ?? "<YOUR_TOKEN>";

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Connect an agent
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Expose this workspace to external AI agents (Claude Code, Cursor,
          Claude Desktop) via the Model Context Protocol. Mint a bearer token,
          paste it into your client config, start using the 12 memory tools.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          href={`/${workspace.slug}/settings/integrations/connectors`}
          className="group"
        >
          <Card className="transition-colors group-hover:bg-accent">
            <CardContent className="flex items-start gap-3 p-4">
              <Plug className="mt-0.5 h-5 w-5 text-muted-foreground" />
              <div>
                <div className="font-medium">Connectors</div>
                <div className="text-xs text-muted-foreground">
                  Pull facts from Google Drive (and more). Each fact inherits
                  its source document&apos;s permissions.
                </div>
              </div>
            </CardContent>
          </Card>
        </Link>
        <Link
          href={`/${workspace.slug}/settings/identity`}
          className="group"
        >
          <Card className="transition-colors group-hover:bg-accent">
            <CardContent className="flex items-start gap-3 p-4">
              <User className="mt-0.5 h-5 w-5 text-muted-foreground" />
              <div>
                <div className="font-medium">Connected identities</div>
                <div className="text-xs text-muted-foreground">
                  Link your source-system accounts so the visibility filter
                  can resolve you against per-document ACLs.
                </div>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4 space-y-0">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">MCP endpoint</CardTitle>
          </div>
          <CopyButton value={url} label="URL" />
        </CardHeader>
        <CardContent>
          <code className="block overflow-x-auto rounded-md border bg-muted/40 px-3 py-2 font-mono text-sm">
            {url}
          </code>
          <p className="mt-2 text-xs text-muted-foreground">
            Send JSON-RPC 2.0 POST requests here with{" "}
            <code className="font-mono">Authorization: Bearer …</code>.
            Discovery metadata lives at{" "}
            <code className="font-mono">
              /.well-known/oauth-protected-resource
            </code>
            .
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4 space-y-0">
          <div className="flex items-center gap-2">
            <Key className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">Tokens</CardTitle>
          </div>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> Create token
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <TokensTable
            rows={tokens.data ?? []}
            onRevoke={(id) => revokeMutation.mutate(id)}
            isRevoking={revokeMutation.isPending}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Client configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="claude-code">
            <TabsList>
              <TabsTrigger value="claude-code">Claude Code</TabsTrigger>
              <TabsTrigger value="cursor">Cursor</TabsTrigger>
              <TabsTrigger value="claude-desktop">Claude Desktop</TabsTrigger>
            </TabsList>

            <TabsContent value="claude-code" className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Run once; the server registers globally (
                <code className="font-mono">--scope user</code>) across all
                projects. Use <code className="font-mono">--scope project</code>{" "}
                instead to commit a <code>.mcp.json</code> with your team.
              </p>
              <Snippet
                value={`claude mcp add-json memory '${JSON.stringify(
                  {
                    type: "http",
                    url,
                    headers: { Authorization: `Bearer ${tokenForSnippets}` },
                  },
                  null,
                  0,
                )}' --scope user`}
              />
            </TabsContent>

            <TabsContent value="cursor" className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Project config:{" "}
                <code className="font-mono">.cursor/mcp.json</code>. Global:{" "}
                <code className="font-mono">~/.cursor/mcp.json</code>.
              </p>
              <Snippet
                value={JSON.stringify(
                  {
                    mcpServers: {
                      memory: {
                        type: "http",
                        url,
                        headers: {
                          Authorization: `Bearer ${tokenForSnippets}`,
                        },
                      },
                    },
                  },
                  null,
                  2,
                )}
              />
            </TabsContent>

            <TabsContent value="claude-desktop" className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Edit{" "}
                <code className="font-mono">
                  ~/Library/Application
                  Support/Claude/claude_desktop_config.json
                </code>{" "}
                on macOS. Restart Claude Desktop afterwards.
              </p>
              <Snippet
                value={JSON.stringify(
                  {
                    mcpServers: {
                      memory: {
                        url,
                        headers: {
                          Authorization: `Bearer ${tokenForSnippets}`,
                        },
                      },
                    },
                  },
                  null,
                  2,
                )}
              />
            </TabsContent>
          </Tabs>
          {!justCreated && (
            <p className="mt-3 text-xs text-muted-foreground">
              Create a token above — the snippets will pre-fill it here for one
              session. We never store the plaintext.
            </p>
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create agent token</DialogTitle>
            <DialogDescription>
              This token grants full MCP access to the current workspace. Keep
              it secret; revoke immediately if it leaks.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
            className="space-y-3"
          >
            <div className="space-y-1">
              <Label htmlFor="token-name">Name</Label>
              <Input
                id="token-name"
                placeholder="Claude Code — laptop"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="token-expiry">Expires</Label>
              <Select
                id="token-expiry"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value as typeof expiry)}
              >
                <option value="never">Never</option>
                <option value="30">In 30 days</option>
                <option value="90">In 90 days</option>
                <option value="365">In 1 year</option>
              </Select>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!justCreated}
        onOpenChange={(o) => !o && setJustCreated(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Warning className="h-4 w-4 text-amber-500" /> Copy your token now
            </DialogTitle>
            <DialogDescription>
              You won&apos;t see it again. If you lose it, create a new one and
              revoke this one.
            </DialogDescription>
          </DialogHeader>
          {justCreated && (
            <div className="space-y-3">
              <code className="block overflow-x-auto rounded-md border bg-muted/60 px-3 py-2 font-mono text-sm">
                {justCreated.token}
              </code>
              <div className="flex justify-end gap-2">
                <CopyButton value={justCreated.token} label="Token" />
                <Button onClick={() => setJustCreated(null)}>Done</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function TokensTable({
  rows,
  onRevoke,
  isRevoking,
}: {
  rows: AgentTokenRow[];
  onRevoke: (id: string) => void;
  isRevoking: boolean;
}) {
  if (rows.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-sm text-muted-foreground">
        No tokens yet. Create one to connect Claude Code or Cursor.
      </div>
    );
  }
  return (
    <ul className="divide-y text-sm">
      {rows.map((t) => {
        const revoked = !!t.revoked_at;
        return (
          <li
            key={t.id}
            className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium">{t.name}</span>
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                  mem_{t.prefix}…
                </code>
                {revoked && (
                  <span className="rounded bg-destructive/15 px-1.5 py-0.5 text-[11px] text-destructive">
                    revoked
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                Created {format(new Date(t.created_at), "yyyy-MM-dd")} ·
                {t.last_used_at
                  ? ` used ${format(new Date(t.last_used_at), "yyyy-MM-dd HH:mm")}`
                  : " never used"}
                {t.expires_at &&
                  ` · expires ${format(new Date(t.expires_at), "yyyy-MM-dd")}`}
              </div>
            </div>
            {!revoked && (
              <Button
                variant="outline"
                size="sm"
                className="border-destructive/40 text-destructive hover:bg-destructive/10"
                onClick={() => {
                  if (
                    typeof window !== "undefined" &&
                    !window.confirm(`Revoke ${t.name}?`)
                  ) {
                    return;
                  }
                  onRevoke(t.id);
                }}
                disabled={isRevoking}
              >
                <Trash className="h-3.5 w-3.5" /> Revoke
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Snippet({ value }: { value: string }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md border bg-muted/40 px-3 py-2 font-mono text-xs leading-relaxed">
        {value}
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton value={value} label="Snippet" />
      </div>
    </div>
  );
}
