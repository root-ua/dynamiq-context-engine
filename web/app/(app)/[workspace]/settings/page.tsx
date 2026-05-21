"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PiUsers, PiWarning } from "react-icons/pi";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import {
  accountApi,
  exportsApi,
  versionApi,
  workspacesApi,
} from "@/lib/api/endpoints";
import { invalidateTokenCache } from "@/lib/api/client";
import { authClient } from "@/lib/auth-client";
import { useWorkspace } from "@/lib/workspace-context";

export default function SettingsPage() {
  const { workspace, refresh } = useWorkspace();
  const router = useRouter();
  const qc = useQueryClient();
  const { push } = useToast();

  const [name, setName] = useState(workspace?.name ?? "");
  const [mode, setMode] = useState<"strict" | "flexible" | "auto">(
    (workspace?.settings?.ontology_mode as "strict" | "flexible" | "auto") ??
      "flexible",
  );
  const [highSensitivity, setHighSensitivity] = useState(
    Boolean(workspace?.high_sensitivity),
  );
  const [saving, setSaving] = useState(false);
  const [exportJobId, setExportJobId] = useState<string | null>(null);
  const [exportStatus, setExportStatus] = useState<
    "idle" | "queued" | "running" | "completed" | "failed"
  >("idle");
  const [exportUrl, setExportUrl] = useState<string | null>(null);

  const [deleteWsOpen, setDeleteWsOpen] = useState(false);
  const [deleteWsSlug, setDeleteWsSlug] = useState("");
  const [deletingWs, setDeletingWs] = useState(false);

  const [resetOpen, setResetOpen] = useState(false);
  const [resetSlug, setResetSlug] = useState("");
  const [resetting, setResetting] = useState(false);

  const [deleteAcctOpen, setDeleteAcctOpen] = useState(false);
  const [deleteAcctConfirm, setDeleteAcctConfirm] = useState("");
  const [deletingAcct, setDeletingAcct] = useState(false);

  async function save() {
    if (!workspace) return;
    setSaving(true);
    try {
      await workspacesApi.update(workspace.id, {
        name,
        ontology_mode: mode,
        high_sensitivity: highSensitivity,
      });
      push({ title: "Settings saved" });
      void refresh();
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
    } catch (err: unknown) {
      push({
        title: "Failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  }

  async function resetWorkspace() {
    if (!workspace) return;
    setResetting(true);
    try {
      const counts = await workspacesApi.debugReset(workspace.id, resetSlug);
      const total = Object.values(counts).reduce(
        (sum, n) => sum + (n > 0 ? n : 0),
        0,
      );
      push({
        title: "Workspace reset",
        description: `Deleted ${total} rows across ${Object.keys(counts).length} tables. You can re-sync Google Docs now.`,
      });
      void qc.invalidateQueries();
      setResetOpen(false);
      setResetSlug("");
    } catch (err) {
      push({
        title: "Couldn't reset workspace",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setResetting(false);
    }
  }

  async function deleteWorkspace() {
    if (!workspace) return;
    setDeletingWs(true);
    try {
      await workspacesApi.remove(workspace.id, deleteWsSlug);
      push({ title: "Workspace deleted" });
      void refresh();
      void qc.invalidateQueries();
      void router.replace("/home");
    } catch (err) {
      push({
        title: "Couldn't delete workspace",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setDeletingWs(false);
    }
  }

  async function signOutEverywhere() {
    try {
      await accountApi.revokeAllSessions();
      invalidateTokenCache();
      await authClient.signOut();
      push({ title: "Signed out everywhere" });
      void router.replace("/login");
    } catch (err) {
      push({
        title: "Couldn't sign out",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  }

  async function deleteAccount() {
    setDeletingAcct(true);
    try {
      await accountApi.deleteAccount();
      invalidateTokenCache();
      await authClient.signOut();
      push({ title: "Account deleted" });
      void router.replace("/");
    } catch (err) {
      push({
        title: "Couldn't delete account",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setDeletingAcct(false);
    }
  }

  if (!workspace) return null;

  const workspaceSlugMatches = deleteWsSlug === workspace.slug;
  const acctConfirmMatches = deleteAcctConfirm === "DELETE";

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Workspace-wide configuration and account controls.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Basics</CardTitle>
          <CardDescription>
            Slug is permanent: <code>{workspace.slug}</code>
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Ontology mode</CardTitle>
          <CardDescription>
            Controls how the extraction pipeline handles types it hasn't seen
            before.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Select
            value={mode}
            onChange={(e) => setMode(e.target.value as typeof mode)}
          >
            <option value="strict">
              Strict — extractor uses only existing types
            </option>
            <option value="flexible">
              Flexible — may introduce a new type when needed
            </option>
            <option value="auto">
              Auto — freely invent new types from content
            </option>
          </Select>
          <p className="text-xs text-muted-foreground">
            In flexible or auto mode, new ontology elements are tagged with
            their source in the audit log so you can review agent-created types.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Privacy</CardTitle>
          <CardDescription>
            Mark a workspace as high-sensitivity to hint to calling agents that
            stricter prompting and human-in-the-loop checks are required.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <Label htmlFor="high-sensitivity">High-sensitivity workspace</Label>
            <p className="text-xs text-muted-foreground">
              Surfaced to MCP clients as a workspace property. Does not
              currently change retrieval behaviour.
            </p>
          </div>
          <Switch
            id="high-sensitivity"
            checked={highSensitivity}
            onChange={(e) => setHighSensitivity(e.target.checked)}
          />
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">MCP agents</CardTitle>
          <CardDescription>
            Mint long-lived tokens to let Claude Code, Cursor, Claude Desktop,
            the Claude web app, or any other MCP-aware client connect to this
            workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={() => router.push(`/${workspace.slug}/settings/agents`)}
          >
            Manage agent tokens
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Data</CardTitle>
          <CardDescription>
            Export every entity, edge, episode, audit row, label, and action
            invocation in this workspace as gzipped JSON-lines.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={async () => {
              try {
                setExportStatus("queued");
                const job = await exportsApi.startWorkspace(workspace.id);
                setExportJobId(job.id);
                setExportStatus(
                  job.status === "completed" ? "completed" : "running",
                );
                if (job.download_url) setExportUrl(job.download_url);
              } catch (err) {
                setExportStatus("failed");
                push({
                  title: "Export failed to start",
                  description: err instanceof Error ? err.message : String(err),
                  variant: "destructive",
                });
              }
            }}
            disabled={exportStatus === "queued" || exportStatus === "running"}
          >
            {exportStatus === "queued" || exportStatus === "running"
              ? "Exporting…"
              : "Export workspace data"}
          </Button>
          {exportJobId && (
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  const job = await exportsApi.pollWorkspace(
                    workspace.id,
                    exportJobId,
                  );
                  setExportStatus(job.status ?? "running");
                  if (job.download_url) setExportUrl(job.download_url);
                } catch (err) {
                  push({
                    title: "Poll failed",
                    description:
                      err instanceof Error ? err.message : String(err),
                    variant: "destructive",
                  });
                }
              }}
            >
              Refresh status
            </Button>
          )}
          {exportUrl && (
            <a
              href={exportUrl}
              className="text-sm underline"
              target="_blank"
              rel="noreferrer"
            >
              Download .jsonl.gz
            </a>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Team</CardTitle>
          <CardDescription>
            Invite teammates, manage roles, revoke pending invites.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" asChild>
            <Link href={`/${workspace.slug}/settings/members`}>
              <PiUsers className="h-4 w-4" /> Manage members
            </Link>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Account</CardTitle>
          <CardDescription>Session controls for your login.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={signOutEverywhere}>
            Sign out everywhere
          </Button>
        </CardContent>
      </Card>

      <BuildInfoCard />

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-destructive">
            <PiWarning className="h-4 w-4" /> Danger zone
          </CardTitle>
          <CardDescription>
            Destructive actions. No undo from the UI.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
          <Button variant="outline" onClick={() => setResetOpen(true)}>
            Reset memory (debug)
          </Button>
          <Button variant="destructive" onClick={() => setDeleteWsOpen(true)}>
            Delete workspace
          </Button>
          <Button variant="destructive" onClick={() => setDeleteAcctOpen(true)}>
            Delete account
          </Button>
        </CardContent>
      </Card>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset workspace memory</DialogTitle>
            <DialogDescription>
              Wipes the graph, episodes, and ontology in{" "}
              <strong>{workspace.name}</strong>. Keeps the workspace, members,
              OAuth connections, sensitivity labels, and audit log. After this,
              re-clicking <em>Sync now</em> on Google Docs re-ingests every doc
              from scratch. No undo.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reset-confirm">
              Type the workspace slug{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                {workspace.slug}
              </code>{" "}
              to confirm:
            </Label>
            <Input
              id="reset-confirm"
              value={resetSlug}
              onChange={(e) => setResetSlug(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setResetOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={resetWorkspace}
              disabled={resetSlug !== workspace.slug || resetting}
            >
              {resetting ? "Resetting…" : "Reset memory"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteWsOpen} onOpenChange={setDeleteWsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete workspace</DialogTitle>
            <DialogDescription>
              This soft-deletes <strong>{workspace.name}</strong> and hides it
              from the switcher. Everyone in the workspace loses access. This is
              reversible within 30 days by support.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="ws-confirm">
              Type the workspace slug{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                {workspace.slug}
              </code>{" "}
              to confirm:
            </Label>
            <Input
              id="ws-confirm"
              value={deleteWsSlug}
              onChange={(e) => setDeleteWsSlug(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteWsOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={deleteWorkspace}
              disabled={!workspaceSlugMatches || deletingWs}
            >
              {deletingWs ? "Deleting…" : "Delete workspace"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteAcctOpen} onOpenChange={setDeleteAcctOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete account</DialogTitle>
            <DialogDescription>
              Permanently deletes your account, sign-in credentials, and removes
              you from all workspaces. Content you authored in workspaces you
              don't own stays with the workspace (attribution is cleared).
              Cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="acct-confirm">
              Type{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                DELETE
              </code>{" "}
              to confirm:
            </Label>
            <Input
              id="acct-confirm"
              value={deleteAcctConfirm}
              onChange={(e) => setDeleteAcctConfirm(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteAcctOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={deleteAccount}
              disabled={!acctConfirmMatches || deletingAcct}
            >
              {deletingAcct ? "Deleting…" : "Delete account"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function BuildInfoCard() {
  const version = useQuery({
    queryKey: ["api-version"],
    queryFn: versionApi.get,
    staleTime: 60_000,
  });
  const v = version.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Build info</CardTitle>
        <CardDescription>
          What this deployment is running. Surface this in support escalations.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <div className="text-muted-foreground">Version</div>
          <div className="font-mono">{v?.version ?? "…"}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Schema</div>
          <div className="font-mono">{v?.schema_version ?? "…"}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Commit</div>
          <div className="font-mono">
            {v?.commit?.slice(0, 12) ?? "(unset — set GIT_SHA in deploy env)"}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Deployed at</div>
          <div className="font-mono">{v?.deployed_at ?? "—"}</div>
        </div>
      </CardContent>
    </Card>
  );
}
