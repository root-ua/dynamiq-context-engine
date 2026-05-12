"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  PiCopySimple as Copy,
  PiTrash as Trash,
  PiLink as LinkIcon,
  PiUserPlus as UserPlus,
} from "react-icons/pi";

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
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import {
  membersApi,
  type WorkspaceInvite,
  type WorkspaceRole,
} from "@/lib/api/endpoints";
import { formatDate } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

export default function MembersPage() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const { push } = useToast();
  const wsId = workspace?.id ?? "";

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteRole, setInviteRole] =
    useState<Exclude<WorkspaceRole, "owner">>("editor");
  const [inviteEmail, setInviteEmail] = useState("");
  const [createdInvite, setCreatedInvite] = useState<WorkspaceInvite | null>(
    null,
  );

  const members = useQuery({
    queryKey: ["members", wsId],
    queryFn: () => membersApi.list(wsId),
    enabled: !!wsId,
  });
  const invites = useQuery({
    queryKey: ["invites", wsId],
    queryFn: () => membersApi.listInvites(wsId),
    enabled: !!wsId,
  });

  const createInvite = useMutation({
    mutationFn: () =>
      membersApi.createInvite(wsId, {
        role: inviteRole,
        invited_email: inviteEmail || undefined,
      }),
    onSuccess: (invite) => {
      setCreatedInvite(invite);
      void qc.invalidateQueries({ queryKey: ["invites", wsId] });
    },
    onError: (err) => {
      push({
        title: "Couldn't create invite",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    },
  });

  const updateRole = useMutation({
    mutationFn: (v: { userId: string; role: WorkspaceRole }) =>
      membersApi.updateRole(wsId, v.userId, v.role),
    onSuccess: () => {
      push({ title: "Role updated" });
      void qc.invalidateQueries({ queryKey: ["members", wsId] });
    },
    onError: (err) => {
      push({
        title: "Couldn't update role",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    },
  });

  const removeMember = useMutation({
    mutationFn: (userId: string) => membersApi.remove(wsId, userId),
    onSuccess: () => {
      push({ title: "Member removed" });
      void qc.invalidateQueries({ queryKey: ["members", wsId] });
    },
    onError: (err) => {
      push({
        title: "Couldn't remove member",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    },
  });

  const revokeInvite = useMutation({
    mutationFn: (inviteId: string) => membersApi.revokeInvite(wsId, inviteId),
    onSuccess: () => {
      push({ title: "Invite revoked" });
      void qc.invalidateQueries({ queryKey: ["invites", wsId] });
    },
  });

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      push({ title: "Link copied" });
    } catch {
      push({
        title: "Copy failed — select + copy manually",
        variant: "destructive",
      });
    }
  }

  if (!workspace) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 md:p-6">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Members</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Invite teammates with a share link. Roles: owner (full), admin
            (manage members), editor (read/write content), viewer (read only).
          </p>
        </div>
        <Button onClick={() => setInviteOpen(true)}>
          <UserPlus className="h-4 w-4" /> Invite
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Active members</CardTitle>
          <CardDescription>{members.data?.length ?? 0} total</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y">
            {(members.data ?? []).map((m) => (
              <li
                key={m.user_id}
                className="flex flex-col gap-2 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-3"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    {m.name || m.email || m.user_id}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {m.email} · joined {formatDate(m.joined_at)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Select
                    value={m.role}
                    disabled={m.role === "owner"}
                    onChange={(e) =>
                      updateRole.mutate({
                        userId: m.user_id,
                        role: e.target.value as WorkspaceRole,
                      })
                    }
                  >
                    <option value="owner">Owner</option>
                    <option value="admin">Admin</option>
                    <option value="editor">Editor</option>
                    <option value="viewer">Viewer</option>
                  </Select>
                  {m.role !== "owner" && (
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Remove"
                      aria-label="Remove member"
                      onClick={() => removeMember.mutate(m.user_id)}
                    >
                      <Trash className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pending invites</CardTitle>
          <CardDescription>
            Link-based. Share the URL with the person — they'll sign up or sign
            in, then land in the workspace.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {(invites.data ?? []).length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={LinkIcon}
                title="No pending invites"
                description="Create one from the Invite button above."
              />
            </div>
          ) : (
            <ul className="divide-y">
              {(invites.data ?? []).map((inv) => {
                const web = inv.url ?? "";
                return (
                  <li
                    key={inv.id}
                    className="flex flex-col gap-2 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">
                        {inv.invited_email ?? "(no email set)"}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {inv.role} · expires {formatDate(inv.expires_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {web && (
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Copy link"
                          aria-label="Copy invite link"
                          onClick={() => copyUrl(web)}
                        >
                          <Copy className="h-4 w-4" />
                        </Button>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Revoke"
                        aria-label="Revoke invite"
                        onClick={() => revokeInvite.mutate(inv.id)}
                      >
                        <Trash className="h-4 w-4" />
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={inviteOpen}
        onOpenChange={(open) => {
          setInviteOpen(open);
          if (!open) {
            setCreatedInvite(null);
            setInviteEmail("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite to {workspace.name}</DialogTitle>
            <DialogDescription>
              Generates a share link. Email is optional — we don't send the
              email; you share the link however you want.
            </DialogDescription>
          </DialogHeader>
          {createdInvite ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Send this link to the person you want to invite:
              </p>
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={createdInvite.url ?? ""}
                  className="font-mono text-xs"
                />
                <Button
                  variant="outline"
                  onClick={() => copyUrl(createdInvite.url ?? "")}
                >
                  Copy
                </Button>
              </div>
              <div className="flex justify-end">
                <Button onClick={() => setInviteOpen(false)}>Done</Button>
              </div>
            </div>
          ) : (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                createInvite.mutate();
              }}
            >
              <div className="space-y-1">
                <Label htmlFor="inv-email">Email (optional)</Label>
                <Input
                  id="inv-email"
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="teammate@example.com"
                />
                <p className="text-xs text-muted-foreground">
                  For your records — we don't send email yet.
                </p>
              </div>
              <div className="space-y-1">
                <Label htmlFor="inv-role">Role</Label>
                <Select
                  id="inv-role"
                  value={inviteRole}
                  onChange={(e) =>
                    setInviteRole(
                      e.target.value as Exclude<WorkspaceRole, "owner">,
                    )
                  }
                >
                  <option value="admin">Admin</option>
                  <option value="editor">Editor</option>
                  <option value="viewer">Viewer</option>
                </Select>
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setInviteOpen(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={createInvite.isPending}>
                  {createInvite.isPending ? "Creating…" : "Create invite"}
                </Button>
              </div>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
