"use client";

import { useQueryClient } from "@tanstack/react-query";
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
import { useToast } from "@/components/ui/toast";
import { accountApi, workspacesApi } from "@/lib/api/endpoints";
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
  const [saving, setSaving] = useState(false);

  const [deleteWsOpen, setDeleteWsOpen] = useState(false);
  const [deleteWsSlug, setDeleteWsSlug] = useState("");
  const [deletingWs, setDeletingWs] = useState(false);

  const [deleteAcctOpen, setDeleteAcctOpen] = useState(false);
  const [deleteAcctConfirm, setDeleteAcctConfirm] = useState("");
  const [deletingAcct, setDeletingAcct] = useState(false);

  async function save() {
    if (!workspace) return;
    setSaving(true);
    try {
      await workspacesApi.update(workspace.id, { name, ontology_mode: mode });
      push({ title: "Settings saved" });
      refresh();
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

  async function deleteWorkspace() {
    if (!workspace) return;
    setDeletingWs(true);
    try {
      await workspacesApi.remove(workspace.id, deleteWsSlug);
      push({ title: "Workspace deleted" });
      refresh();
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

      <div className="flex justify-end">
        <Button onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>

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
          <Button variant="destructive" onClick={() => setDeleteWsOpen(true)}>
            Delete workspace
          </Button>
          <Button variant="destructive" onClick={() => setDeleteAcctOpen(true)}>
            Delete account
          </Button>
        </CardContent>
      </Card>

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
