"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  PiArrowsClockwise,
  PiCheckCircle,
  PiFile,
  PiLink,
  PiPencilSimple,
  PiPlugsConnected,
  PiTrash,
  PiWarningCircle,
} from "react-icons/pi";

import { GoogleDrivePicker } from "@/components/integrations/GoogleDrivePicker";
import { SyncProgress } from "@/components/integrations/SyncProgress";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { googleDocsApi } from "@/lib/api/endpoints";
import type {
  GoogleDocSyncState,
  GoogleDriveConnectionSummary,
} from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

/**
 * Google Docs integration page.
 *
 * Three visual states, gated by data:
 * 1. No connection → "Connect Google" button (kicks off OAuth redirect).
 * 2. Connection exists, no selection → folder picker + "Add to workspace".
 * 3. Connection + saved selection → compact selection summary + "Re-sync"
 *    primary CTA, with an "Edit selection" link that swaps the picker
 *    back in. Sync progress renders in-place of the CTA on the same card.
 *
 * URL params after the OAuth callback:
 *   ?connected=1&connection_id=<uuid>
 *   ?error=<reason>
 */
export default function GoogleDocsIntegrationPage() {
  const { workspace } = useWorkspace();
  const params = useSearchParams();
  const toast = useToast();
  const queryClient = useQueryClient();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";

  // Surface OAuth-callback outcome via toast.
  useEffect(() => {
    const error = params.get("error");
    const connected = params.get("connected");
    if (error) {
      toast.push({
        title: `Google connection failed: ${error}`,
        variant: "destructive",
      });
    } else if (connected) {
      toast.push({ title: "Google account connected." });
    }
  }, [params, toast]);

  const connectionsQuery = useQuery({
    queryKey: ["gdocs-connections", wsId],
    queryFn: () => googleDocsApi.listConnections(wsId),
    enabled: !!wsId,
  });

  const connection: GoogleDriveConnectionSummary | undefined =
    connectionsQuery.data?.data?.[0];
  const connectionId = connection?.id ?? "";

  // -------- Connect / disconnect --------

  const startAuthMutation = useMutation({
    mutationFn: () =>
      googleDocsApi.authorize(wsId, `/${wsSlug}/integrations/google-docs`),
    onSuccess: (resp) => {
      window.location.href = resp.authorize_url;
    },
    onError: (e: Error) =>
      toast.push({
        title: `Failed to start OAuth: ${e.message}`,
        variant: "destructive",
      }),
  });

  const revokeMutation = useMutation({
    mutationFn: () => googleDocsApi.revokeConnection(wsId, connectionId),
    onSuccess: () => {
      toast.push({ title: "Google account disconnected." });
      void queryClient.invalidateQueries({
        queryKey: ["gdocs-connections", wsId],
      });
    },
    onError: (e: Error) =>
      toast.push({
        title: `Disconnect failed: ${e.message}`,
        variant: "destructive",
      }),
  });

  // -------- Selection draft (live from picker) --------

  const [draftSelection, setDraftSelection] = useState<{
    folders: { id: string; name: string }[];
    files: { id: string; name: string }[];
  } | null>(null);

  const initialSelection = useMemo(
    () => connection?.selection ?? { folders: [], files: [] },
    [connection?.selection],
  );

  // -------- Sync job (renders inline in the picker card) --------

  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // -------- Add to workspace (save + sync, atomically from the user's POV) --------

  const addToWorkspaceMutation = useMutation({
    mutationFn: async () => {
      // Save first — fail loudly if PUT fails so we don't half-start a sync.
      const updated = await googleDocsApi.saveSelection(
        wsId,
        connectionId,
        draftSelection ?? initialSelection,
      );
      // Then kick the worker. The two calls are intentionally chained on
      // the client; the backend doesn't offer a combined endpoint.
      const jobResp = await googleDocsApi.startSync(wsId, connectionId);
      return { updated, job: jobResp.data };
    },
    onSuccess: ({ updated, job }) => {
      // Replace the cache wholesale with the server response so
      // hasSavedSelection flips synchronously on this render. v1 only
      // ever has one connection per workspace, so a list-by-index
      // replacement is correct; using a by-id filter risked silent
      // no-ops if the cached list and the response disagreed on the id
      // shape (UUID vs. string).
      queryClient.setQueryData(["gdocs-connections", wsId], {
        data: [updated],
      });
      // Also invalidate in the background so a fresh GET reconciles
      // anything we may have missed (e.g. updated_at timestamp).
      void queryClient.invalidateQueries({
        queryKey: ["gdocs-connections", wsId],
      });
      setDraftSelection(null);
      setActiveJobId(job.id);
      setEditing(false);
      toast.push({ title: "Sync started." });
    },
    onError: (e: Error) =>
      toast.push({
        title: `Couldn't add to workspace: ${e.message}`,
        variant: "destructive",
      }),
  });

  // -------- Re-sync only (no selection change) --------

  const reSyncMutation = useMutation({
    mutationFn: () => googleDocsApi.startSync(wsId, connectionId),
    onSuccess: (resp) => {
      setActiveJobId(resp.data.id);
      toast.push({ title: "Sync started." });
    },
    onError: (e: Error) =>
      toast.push({
        title: `Sync failed to start: ${e.message}`,
        variant: "destructive",
      }),
  });

  const docsQuery = useQuery({
    queryKey: ["gdocs-docs", connectionId],
    queryFn: () => googleDocsApi.listDocs(wsId, connectionId),
    enabled: !!connectionId,
  });

  // -------- Picker edit-mode toggle --------
  //
  // Default to edit mode iff there's no saved selection yet — a fresh
  // user lands directly in the tree. A returning user with a saved
  // selection sees the compact re-sync state instead.
  const hasSavedSelection =
    (connection?.selection.folders.length ?? 0) > 0 ||
    (connection?.selection.files.length ?? 0) > 0;
  const [editing, setEditing] = useState<boolean>(!hasSavedSelection);

  // When the connection arrives (or hasSavedSelection flips because of
  // a successful save), reconcile the default. We only force-collapse
  // back to summary when the user has saved something AND there is no
  // unsaved draft AND no active job in flight.
  useEffect(() => {
    if (
      hasSavedSelection &&
      draftSelection === null &&
      !addToWorkspaceMutation.isPending
    ) {
      setEditing(false);
    } else if (!hasSavedSelection) {
      setEditing(true);
    }
    // We intentionally don't depend on `editing` itself to avoid
    // fighting the user's manual toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasSavedSelection, connectionId]);

  if (!workspace) return null;

  // ---------- Early states ----------

  if (connectionsQuery.isLoading) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-8">
        <div className="text-sm text-muted-foreground">
          Loading your Google connection…
        </div>
      </div>
    );
  }

  if (!connection) {
    return (
      <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <Header />
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Connect Google</CardTitle>
            <CardDescription>
              Click the button below to authorize this workspace to read your
              Google Drive. You'll see Google's standard consent screen. We only
              request <code>drive.readonly</code> — we never write or delete
              your files.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              onClick={() => startAuthMutation.mutate()}
              disabled={startAuthMutation.isPending}
              className="gap-2"
            >
              <PiLink className="size-4" />
              {startAuthMutation.isPending ? "Redirecting…" : "Connect Google"}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------- Derived counts ----------

  const draftFolderCount = draftSelection?.folders.length ?? 0;
  const draftFileCount = draftSelection?.files.length ?? 0;
  const draftTotal = draftFolderCount + draftFileCount;

  const savedFolderCount = connection.selection.folders.length;
  const savedFileCount = connection.selection.files.length;
  const savedTotal = savedFolderCount + savedFileCount;

  // What counts to show on the CTA: the unsaved draft if it exists,
  // otherwise the saved selection. The CTA shape (Add vs. Re-sync) is
  // determined by whether a saved selection exists.
  const ctaCount = draftSelection !== null ? draftTotal : savedTotal;

  const liveCounterText =
    draftSelection !== null
      ? formatCounter(draftFolderCount, draftFileCount)
      : formatCounter(savedFolderCount, savedFileCount);

  const syncInFlight =
    activeJobId !== null &&
    !!docsQuery.data?.data.some(
      (d) => d.status === "syncing" || d.status === "pending",
    );

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
      <Header />

      {/* Connection status (with inline workspace-trust pill) */}
      <Card>
        <CardContent className="space-y-3 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-md bg-emerald-50 dark:bg-emerald-950">
                <PiPlugsConnected className="size-4 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div>
                <div className="text-sm font-medium">
                  Connected as {connection.account_email}
                </div>
                <div className="text-xs text-muted-foreground">
                  Since {formatDate(connection.created_at)}
                </div>
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (confirm("Disconnect Google? Synced docs stay in memory.")) {
                  revokeMutation.mutate();
                }
              }}
              disabled={revokeMutation.isPending}
            >
              <PiTrash className="mr-1 size-4" /> Disconnect
            </Button>
          </div>
          <div className="inline-flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50/60 px-2 py-1 text-[11px] text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            <PiWarningCircle className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Anything you sync is visible to all members of{" "}
              <code className="font-mono">{workspace.slug}</code>. Per-doc Drive
              permissions are stored but not enforced at retrieval (v2).
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Pick + add (one card, two steps) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {hasSavedSelection && !editing
              ? "Synced from Drive"
              : "What to ingest"}
          </CardTitle>
          <CardDescription>
            {hasSavedSelection && !editing
              ? "These items are tracked for this workspace. Re-syncing pulls any updates from Drive."
              : "Pick folders or individual Google Docs. Selecting a folder syncs every Google Doc inside it (recursively)."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {editing ? (
            <>
              <GoogleDrivePicker
                workspaceId={wsId}
                connectionId={connectionId}
                initialSelection={initialSelection}
                onChange={setDraftSelection}
              />
              <div className="text-xs text-muted-foreground">
                {liveCounterText} selected
              </div>
            </>
          ) : (
            <SavedSelectionSummary
              folders={connection.selection.folders}
              files={connection.selection.files}
            />
          )}

          {/* Single primary action / live sync, mutually exclusive */}
          {activeJobId ? (
            <SyncProgress
              workspaceId={wsId}
              jobId={activeJobId}
              connectionId={connectionId}
              onDone={() => {
                void queryClient.invalidateQueries({
                  queryKey: ["gdocs-docs", connectionId],
                });
              }}
            />
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              {hasSavedSelection && !editing ? (
                <>
                  <Button
                    onClick={() => reSyncMutation.mutate()}
                    disabled={reSyncMutation.isPending || syncInFlight}
                    className="gap-2"
                  >
                    <PiArrowsClockwise className="size-4" />
                    {reSyncMutation.isPending
                      ? "Starting…"
                      : `Re-sync ${ctaCount} item${ctaCount === 1 ? "" : "s"}`}
                  </Button>
                  <button
                    type="button"
                    onClick={() => setEditing(true)}
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    <PiPencilSimple className="size-3.5" />
                    Edit selection
                  </button>
                </>
              ) : (
                <>
                  <Button
                    onClick={() => addToWorkspaceMutation.mutate()}
                    disabled={
                      addToWorkspaceMutation.isPending ||
                      // Nothing chosen at all — block.
                      ctaCount === 0
                    }
                    className="gap-2"
                  >
                    <PiCheckCircle className="size-4" />
                    {addToWorkspaceMutation.isPending
                      ? "Adding…"
                      : `Add ${ctaCount} item${ctaCount === 1 ? "" : "s"} to workspace`}
                  </Button>
                  {hasSavedSelection && (
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(false);
                        setDraftSelection(null);
                      }}
                      className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Cancel
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Per-doc status list */}
      {docsQuery.data && docsQuery.data.data.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Synced documents</CardTitle>
            <CardDescription>
              {docsQuery.data.data.length} doc
              {docsQuery.data.data.length === 1 ? "" : "s"} known to this
              workspace.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DocList docs={docsQuery.data.data} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Header() {
  return (
    <div>
      <h1 className="flex items-center gap-2 text-xl font-semibold">
        <PiFile className="size-5" /> Google Docs
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Pull Google Docs into this workspace's memory.
      </p>
    </div>
  );
}

/**
 * Compact human-readable counter for the picker, e.g.
 * "3 folders, 12 docs". Falls back to "Nothing" so the label stays
 * grammatical when the picker is empty.
 */
function formatCounter(folderCount: number, fileCount: number): string {
  if (folderCount === 0 && fileCount === 0) return "Nothing";
  const parts: string[] = [];
  if (folderCount > 0) {
    parts.push(`${folderCount} folder${folderCount === 1 ? "" : "s"}`);
  }
  if (fileCount > 0) {
    parts.push(`${fileCount} doc${fileCount === 1 ? "" : "s"}`);
  }
  return parts.join(", ");
}

function SavedSelectionSummary({
  folders,
  files,
}: {
  folders: { id: string; name: string }[];
  files: { id: string; name: string }[];
}) {
  if (folders.length === 0 && files.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">Nothing selected yet.</div>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {folders.map((f) => (
        <span
          key={`folder-${f.id}`}
          className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 text-xs"
          title={f.name}
        >
          <PiFile className="size-3 opacity-70" />
          {f.name}
        </span>
      ))}
      {files.map((f) => (
        <span
          key={`file-${f.id}`}
          className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 text-xs"
          title={f.name}
        >
          <PiFile className="size-3 opacity-70" />
          {f.name}
        </span>
      ))}
    </div>
  );
}

function DocList({ docs }: { docs: GoogleDocSyncState[] }) {
  return (
    <div className="divide-y text-sm">
      {docs.map((d) => (
        <div key={d.id} className="flex items-center gap-3 py-2">
          <PiFile className="size-3.5 shrink-0 text-muted-foreground" />
          <span
            className="flex-1 truncate"
            title={d.doc_title ?? d.google_doc_id}
          >
            {d.doc_title ?? d.google_doc_id}
          </span>
          <DocStatusBadge status={d.status} />
          {d.last_synced_at && (
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatDate(d.last_synced_at)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function DocStatusBadge({ status }: { status: GoogleDocSyncState["status"] }) {
  const styles: Record<GoogleDocSyncState["status"], string> = {
    pending: "bg-muted text-muted-foreground",
    syncing: "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
    completed:
      "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    failed: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
    skipped: "bg-muted text-muted-foreground",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${styles[status]}`}
    >
      {status}
    </span>
  );
}
