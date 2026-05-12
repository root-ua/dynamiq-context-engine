"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PiCaretDown, PiPlus, PiCheck } from "react-icons/pi";

import { Button } from "@/components/ui/button";
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
import { workspacesApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";
import { slugify } from "@/lib/utils-slug";
import { useWorkspace } from "@/lib/workspace-context";

export function WorkspaceSwitcher() {
  const { workspace, workspaces, setWorkspaceId, refresh } = useWorkspace();
  const router = useRouter();
  const { push } = useToast();
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [mode, setMode] = useState<"strict" | "flexible" | "auto">("flexible");
  const [submitting, setSubmitting] = useState(false);

  function pick(id: string, targetSlug: string) {
    setWorkspaceId(id);
    setOpen(false);
    void router.push(`/${targetSlug}`);
  }

  async function createWorkspace(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const ws = await workspacesApi.create({
        slug,
        name,
        ontology_mode: mode,
      });
      push({ title: "Workspace created" });
      setCreateOpen(false);
      setName("");
      setSlug("");
      setWorkspaceId(ws.id);
      refresh();
      void router.push(`/${ws.slug}`);
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

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-md border bg-card px-3 py-2 text-left text-sm transition-colors hover:bg-accent/60"
      >
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">
            {workspace?.name ?? "No workspace"}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {workspace?.slug}
          </div>
        </div>
        <PiCaretDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute inset-x-0 top-full z-50 mt-1 rounded-md border bg-popover p-1 shadow-md">
          {workspaces.map((w) => (
            <button
              type="button"
              key={w.id}
              onClick={() => pick(w.id, w.slug)}
              className={cn(
                "flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent",
                w.id === workspace?.id && "bg-accent/50",
              )}
            >
              <div>
                <div>{w.name}</div>
                <div className="text-xs text-muted-foreground">{w.slug}</div>
              </div>
              {w.id === workspace?.id && <PiCheck className="h-3.5 w-3.5" />}
            </button>
          ))}
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setCreateOpen(true);
            }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent"
          >
            <PiPlus className="h-3.5 w-3.5" /> New workspace
          </button>
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New workspace</DialogTitle>
            <DialogDescription>
              Each workspace has its own ontology, entities, and agent sessions.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={createWorkspace} className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="ws-name">Name</Label>
              <Input
                id="ws-name"
                required
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slug) setSlug(slugify(e.target.value));
                }}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ws-slug">Slug</Label>
              <Input
                id="ws-slug"
                required
                pattern="[a-z0-9-]+"
                value={slug}
                onChange={(e) => setSlug(e.target.value.toLowerCase())}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ws-mode">Ontology mode</Label>
              <Select
                id="ws-mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as typeof mode)}
              >
                <option value="strict">Strict — only the built-in types</option>
                <option value="flexible">
                  Flexible — extractor can add new types
                </option>
                <option value="auto">
                  Auto — freely invent types from content
                </option>
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
