"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useState } from "react";
import {
  PiArrowLeft as ArrowLeft,
  PiLinkSimple as Link2,
  PiSlidersHorizontal as Sliders,
  PiTrash as Trash,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { PropsForm } from "@/components/entity/PropsForm";
import { documentsApi, entitiesApi, ontologyApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

// BlockNote + Yjs are DOM-only. Load client-side to avoid SSR issues.
const Editor = dynamic(
  () => import("@/components/editor/Editor").then((m) => m.Editor),
  {
    ssr: false,
    loading: () => <EditorSkeleton />,
  },
);

/**
 * Minimal skeleton shown while the Editor bundle is still downloading.
 * Matches the live editor's header + body dimensions so the subsequent
 * swap doesn't jump.
 */
function EditorSkeleton() {
  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between gap-2 border-b bg-background/80 px-4 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 font-medium text-amber-700">
            Connecting
          </span>
          <span className="h-3 w-32 animate-pulse rounded bg-muted" />
        </div>
      </div>
      <div className="space-y-3 px-4 py-6">
        <div className="h-4 w-5/6 animate-pulse rounded bg-muted" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
      </div>
    </div>
  );
}

export default function DocumentEditorPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const router = useRouter();
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const qc = useQueryClient();
  const { push } = useToast();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const doc = useQuery({
    queryKey: ["document", wsId, id],
    queryFn: () => documentsApi.get(wsId, id),
    enabled: !!wsId && !!id,
  });

  const entity = useQuery({
    queryKey: ["entity", wsId, doc.data?.entity_id],
    queryFn: () => entitiesApi.get(wsId, doc.data!.entity_id),
    enabled: !!doc.data,
  });

  const types = useQuery({
    queryKey: ["ontology", wsId, "types"],
    queryFn: () => ontologyApi.listTypes(wsId),
    enabled: !!wsId,
    staleTime: 60_000,
  });

  const backlinks = useQuery({
    queryKey: ["doc-entity-backlinks", wsId, id, doc.data?.entity_id],
    queryFn: () =>
      doc.data
        ? entitiesApi.backlinks(wsId, doc.data.entity_id)
        : Promise.resolve([]),
    enabled: !!doc.data,
  });

  const entityType =
    types.data?.find((t) => t.slug === doc.data?.type_slug) ?? null;

  const [title, setTitle] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (!workspace || !id) return null;
  const base = `/${workspace.slug}`;

  if (doc.isError) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Document not found.
      </div>
    );
  }

  const docData = doc.data;
  const entityData = entity.data;
  const currentTitle = title ?? docData?.title ?? "";

  async function saveTitle() {
    if (!docData || title == null || title === docData.title) return;
    setSaving(true);
    try {
      await entitiesApi.update(wsId, docData.entity_id, { canonical: title });
      push({ title: "Title updated" });
      void qc.invalidateQueries({ queryKey: ["document", wsId, id] });
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

  async function deleteDoc() {
    if (!workspace) return;
    setDeleting(true);
    try {
      await documentsApi.remove(wsId, id);
      push({ title: "Document deleted" });
      void qc.invalidateQueries({ queryKey: ["documents", wsId] });
      void router.replace(`/${workspace.slug}/documents`);
    } catch (err) {
      push({
        title: "Failed to delete",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setDeleting(false);
    }
  }

  async function handlePropsChange(next: Record<string, unknown>) {
    if (!docData) return;
    try {
      await entitiesApi.update(wsId, docData.entity_id, { props: next });
      void qc.invalidateQueries({
        queryKey: ["entity", wsId, docData.entity_id],
      });
    } catch (err: unknown) {
      push({
        title: "Failed to save properties",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-[1400px] grid-cols-1 gap-6 p-4 md:p-6 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0 space-y-3">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" asChild>
            <Link href={`${base}/documents`}>
              <ArrowLeft className="h-4 w-4" /> All documents
            </Link>
          </Button>
          {docData?.type_slug && (
            <Badge variant="outline">{docData.type_slug}</Badge>
          )}
          {saving && (
            <span className="text-xs text-muted-foreground">Saving title…</span>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto text-muted-foreground hover:text-destructive"
            onClick={() => setDeleteOpen(true)}
            title="Delete document"
            aria-label="Delete document"
          >
            <Trash className="h-4 w-4" />
          </Button>
        </div>

        <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete this document?</DialogTitle>
              <DialogDescription>
                The document, its block tree, and all @mention backlinks will be
                removed from the workspace. This can't be undone from the UI.
              </DialogDescription>
            </DialogHeader>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={deleteDoc}
                disabled={deleting}
              >
                {deleting ? "Deleting…" : "Delete"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>

        <div className="mx-auto w-full max-w-[820px]">
          <Input
            className="h-auto border-none px-0 !text-[1.75rem] font-semibold leading-tight shadow-none focus-visible:ring-0"
            value={currentTitle}
            placeholder={docData ? "Untitled" : "Loading title…"}
            disabled={!docData}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                (e.target as HTMLInputElement).blur();
              }
            }}
          />

          <div className="mt-3 overflow-hidden rounded-lg border bg-card">
            <Editor
              documentId={id}
              entityId={docData?.entity_id}
              title={currentTitle}
            />
          </div>
        </div>
      </div>

      <aside className="space-y-4">
        <div className="rounded-lg border bg-card/50 p-3">
          <div className="flex items-center gap-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            <Sliders className="h-3 w-3" /> Properties
          </div>
          <div className="mt-2">
            {entityData ? (
              <PropsForm
                schema={entityType?.schema ?? null}
                value={entityData.props}
                onChange={handlePropsChange}
              />
            ) : (
              <div className="space-y-2 pt-1">
                <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
                <div className="h-8 w-full animate-pulse rounded bg-muted" />
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border bg-card/50 p-3">
          <div className="flex items-center gap-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            <Link2 className="h-3 w-3" /> Linked entities
          </div>
          <div className="mt-2 space-y-0.5 text-sm">
            {backlinks.data && backlinks.data.length > 0 ? (
              backlinks.data.map((b) => (
                <Link
                  key={b.block_id}
                  className="block truncate rounded-md px-2 py-1.5 transition-colors hover:bg-accent"
                  href={`${base}/entities/${b.document_id}`}
                >
                  {b.document_title}
                </Link>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">
                Mentions appear here as you type @.
              </p>
            )}
          </div>
        </div>

        <div className="rounded-lg border bg-card/50 p-3 text-xs text-muted-foreground">
          <div className="mb-1 font-semibold text-foreground">
            Collaboration
          </div>
          <p>Changes sync in real time via Yjs. Autosaves every 1.5 seconds.</p>
        </div>
      </aside>
    </div>
  );
}
