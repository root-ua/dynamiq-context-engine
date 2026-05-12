"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  PiFileText as FileText,
  PiPlus as Plus,
  PiMagnifyingGlass as Search,
  PiUploadSimple as Upload,
} from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { getToken } from "@/lib/api/client";
import { documentsApi, ontologyApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

// Warm the Editor bundle in the background as soon as the documents list
// mounts. Opening any document afterwards skips the 1–3s dynamic-import
// wait. Dedupes automatically if already resolved.
if (typeof window !== "undefined") {
  void import("@/components/editor/Editor");
}

export default function DocumentsPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const router = useRouter();
  const qc = useQueryClient();
  const { push } = useToast();

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [typeSlug, setTypeSlug] = useState("note");
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const docs = useQuery({
    queryKey: ["documents", wsId, query],
    queryFn: () => documentsApi.list(wsId, query || undefined),
    enabled: !!wsId,
  });

  const types = useQuery({
    queryKey: ["ontology", wsId, "types"],
    queryFn: () => ontologyApi.listTypes(wsId),
    enabled: !!wsId,
  });

  const contentTypes = (types.data ?? []).filter(
    (t) => !t.ui_hints?.abstract && t.hierarchy.includes("content"),
  );

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-selecting same file
    if (!workspace || files.length === 0) return;
    setUploading(true);
    try {
      const results = await Promise.allSettled(
        files.map((f) => documentsApi.upload(wsId, f)),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.length - ok;
      void qc.invalidateQueries({ queryKey: ["documents", wsId] });
      if (ok) push({ title: `Uploaded ${ok} ${ok === 1 ? "file" : "files"}` });
      if (failed) {
        const firstErr = results.find(
          (r): r is PromiseRejectedResult => r.status === "rejected",
        );
        push({
          title: `${failed} upload${failed === 1 ? "" : "s"} failed`,
          description:
            firstErr?.reason instanceof Error
              ? firstErr.reason.message
              : String(firstErr?.reason ?? ""),
          variant: "destructive",
        });
      }
    } finally {
      setUploading(false);
    }
  }

  async function createDoc(e: React.FormEvent) {
    e.preventDefault();
    if (!workspace) return;
    setSubmitting(true);
    try {
      const doc = await documentsApi.create(wsId, { title, type: typeSlug });
      void qc.invalidateQueries({ queryKey: ["documents", wsId] });
      push({ title: "Document created" });
      setOpen(false);
      setTitle("");
      void router.push(`/${workspace.slug}/documents/${doc.id}`);
    } catch (err: unknown) {
      push({
        title: "Failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  }

  if (!workspace) return null;
  const base = `/${workspace.slug}`;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Collaborate on notes and documents. Mention entities with @ to
            connect them to the graph.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".txt,.md,.markdown,.mdx,text/plain,text/markdown"
            multiple
            onChange={onUpload}
          />
          <Button
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Upload className="h-4 w-4" />
            {uploading ? "Uploading…" : "Upload"}
          </Button>
          <Button onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" /> New document
          </Button>
        </div>
      </div>

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title…"
          className="pl-8"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {(docs.data ?? []).length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={FileText}
                title="No documents yet"
                description="Create a note to start capturing thoughts. Anything you mention becomes a typed entity in the graph."
                action={
                  <Button onClick={() => setOpen(true)}>
                    <Plus className="h-4 w-4" /> New document
                  </Button>
                }
              />
            </div>
          ) : (
            <ul className="divide-y">
              {(docs.data ?? []).map((d) => {
                const warm = () => {
                  // Warm the doc REST cache, the collab JWT cache, and the
                  // Editor bundle — all idempotent, all cheap. Clicking the
                  // link afterwards opens the doc without any cold waits.
                  void qc.prefetchQuery({
                    queryKey: ["document", wsId, d.id],
                    queryFn: () => documentsApi.get(wsId, d.id),
                    staleTime: 30_000,
                  });
                  void getToken(wsId);
                };
                return (
                  <li key={d.id}>
                    <Link
                      className="flex flex-col gap-1 px-4 py-3 text-sm transition-colors hover:bg-accent sm:flex-row sm:items-center sm:justify-between sm:gap-3"
                      href={`${base}/documents/${d.id}`}
                      onMouseEnter={warm}
                      onFocus={warm}
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium">
                          {d.title || "Untitled"}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {d.type_slug}
                        </div>
                      </div>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatDateTime(d.updated_at)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New document</DialogTitle>
            <DialogDescription>
              Creates a new document-backed entity and a Yjs-synced editor
              session.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={createDoc} className="space-y-3">
            <div className="space-y-1">
              <Label>Title</Label>
              <Input
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label>Type</Label>
              <Select
                value={typeSlug}
                onChange={(e) => setTypeSlug(e.target.value)}
              >
                <option value="note">Note</option>
                {contentTypes
                  .filter((t) => t.slug !== "note")
                  .map((t) => (
                    <option key={t.id} value={t.slug}>
                      {t.name}
                    </option>
                  ))}
              </Select>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
