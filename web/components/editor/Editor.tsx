"use client";
import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import { useTheme } from "next-themes";
import * as Y from "yjs";
import {
  PiCheckCircle,
  PiCloudSlash,
  PiSpinnerGap,
  PiArrowsClockwise,
} from "react-icons/pi";

import "@blocknote/core/fonts/inter.css";
import "@blocknote/mantine/style.css";

import { cn } from "@/lib/utils";
import { documentsApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";
import { useToast } from "@/components/ui/toast";
import { memorySchema } from "@/components/editor/schema";
import { SlashMenu } from "@/components/editor/SlashMenu";
import { projectEditor } from "@/components/editor/serialize";
import {
  createCollabProvider,
  type CollabStatus,
} from "@/components/editor/collab";

interface EditorProps {
  documentId: string;
  // Optional: filled in from the doc query after the initial paint. The
  // editor itself only needs `documentId` to connect — we accept entityId
  // asynchronously so we can mount the editor before the REST fetch
  // completes and overlap the WS handshake with the data fetch.
  entityId?: string;
  title?: string;
}

const SAVE_DEBOUNCE_MS = 1500;

/** Stable per-client user color for the Yjs awareness cursor. */
function pickUserColor(): string {
  const palette = [
    "#ef4444",
    "#f97316",
    "#eab308",
    "#22c55e",
    "#06b6d4",
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
  ];
  if (typeof window === "undefined") return palette[0]!;
  const key = "memory:collab:color";
  const stored = window.localStorage.getItem(key);
  if (stored) return stored;
  const color = palette[Math.floor(Math.random() * palette.length)]!;
  window.localStorage.setItem(key, color);
  return color;
}

interface SavedIndicatorProps {
  savedAt: Date | null;
  saving: boolean;
  error: string | null;
}

function SavedIndicator({ savedAt, saving, error }: SavedIndicatorProps) {
  const [relative, setRelative] = React.useState<string>("");

  React.useEffect(() => {
    if (!savedAt) {
      setRelative("");
      return;
    }
    const update = () => {
      const diff = Math.max(
        0,
        Math.round((Date.now() - savedAt.getTime()) / 1000),
      );
      if (diff < 5) setRelative("just now");
      else if (diff < 60) setRelative(`${diff} seconds ago`);
      else if (diff < 3600) setRelative(`${Math.floor(diff / 60)} min ago`);
      else setRelative(`${Math.floor(diff / 3600)} h ago`);
    };
    update();
    const handle = setInterval(update, 5_000);
    return () => clearInterval(handle);
  }, [savedAt]);

  if (error) {
    return (
      <span className="flex items-center gap-1 text-destructive">
        <PiCloudSlash className="h-3.5 w-3.5" /> Save failed
      </span>
    );
  }
  if (saving) {
    return (
      <span className="flex items-center gap-1 text-muted-foreground">
        <PiSpinnerGap className="h-3.5 w-3.5 animate-spin" /> Saving…
      </span>
    );
  }
  if (savedAt) {
    return (
      <span className="flex items-center gap-1 text-muted-foreground">
        <PiCheckCircle className="h-3.5 w-3.5 text-emerald-500" />
        Saved · {relative}
      </span>
    );
  }
  return <span className="text-muted-foreground">Ready</span>;
}

function StatusBadge({ status }: { status: CollabStatus }) {
  const label =
    status === "connected"
      ? "Live"
      : status === "connecting"
        ? "Connecting"
        : status === "reconnecting"
          ? "Reconnecting"
          : "Offline";
  const tone =
    status === "connected"
      ? "bg-emerald-500/15 text-emerald-700 border-emerald-500/30"
      : status === "offline"
        ? "bg-destructive/15 text-destructive border-destructive/30"
        : "bg-amber-500/15 text-amber-700 border-amber-500/30";
  const Icon =
    status === "offline"
      ? PiCloudSlash
      : status === "connected"
        ? PiCheckCircle
        : PiArrowsClockwise;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        tone,
      )}
    >
      <Icon
        className={cn(
          "h-3 w-3",
          status === "connecting" || status === "reconnecting"
            ? "animate-spin"
            : "",
        )}
      />
      {label}
    </span>
  );
}

export function Editor({ documentId, entityId, title }: EditorProps) {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
  const queryClient = useQueryClient();
  const toast = useToast();

  // Resolve theme after mount to avoid a light-to-dark flash during
  // hydration. Before mount we intentionally default to "light" so
  // server-rendered markup matches the client's first paint.
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  const editorTheme: "light" | "dark" =
    mounted && resolvedTheme === "dark" ? "dark" : "light";

  // A stable Y.Doc per editor instance. Recreated when documentId changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- dep pins the memo to documentId identity, even though the factory doesn't read it.
  const ydoc = React.useMemo(() => new Y.Doc(), [documentId]);

  const [status, setStatus] = React.useState<CollabStatus>("connecting");

  // Hocuspocus provider bound to this document's room. Tying creation to
  // ydoc identity guarantees that a new doc (after route change) gets a
  // fresh provider instance; the cleanup effect below tears the old one
  // down.
  const collab = React.useMemo(
    () =>
      createCollabProvider({
        documentId,
        ydoc,
        onStatusChange: setStatus,
      }),
    [documentId, ydoc],
  );

  React.useEffect(() => {
    return () => {
      collab.destroy();
      ydoc.destroy();
    };
  }, [collab, ydoc]);

  const provider = collab.provider;

  const userColor = React.useMemo(() => pickUserColor(), []);
  const userName = React.useMemo(() => {
    if (typeof window === "undefined") return "Anonymous";
    return window.localStorage.getItem("memory:display-name") || "Anonymous";
  }, []);

  const editor = useCreateBlockNote({
    schema: memorySchema,
    collaboration: {
      provider,
      fragment: ydoc.getXmlFragment("document-store"),
      user: { name: userName, color: userColor },
    },
  });

  // Save bookkeeping.
  const [saving, setSaving] = React.useState(false);
  const [savedAt, setSavedAt] = React.useState<Date | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const saveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = React.useRef<Promise<void> | null>(null);

  const doSave = React.useCallback(async () => {
    if (!workspaceId) return;
    const snapshot = projectEditor(editor);
    setSaving(true);
    setSaveError(null);
    const run = (async () => {
      try {
        await documentsApi.replaceBlocks(workspaceId, documentId, snapshot);
        setSavedAt(new Date());
        void queryClient.invalidateQueries({
          queryKey: ["documents", documentId, "blocks"],
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "unknown error";
        setSaveError(message);
        toast.push({
          title: "Autosave failed",
          description: message,
          variant: "destructive",
        });
      } finally {
        setSaving(false);
        inFlight.current = null;
      }
    })();
    inFlight.current = run;
    await run;
  }, [editor, workspaceId, documentId, queryClient, toast]);

  const scheduleSave = React.useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveTimer.current = null;
      void doSave();
    }, SAVE_DEBOUNCE_MS);
  }, [doSave]);

  // Hook BlockNote's change stream into the debounced save. Skip the
  // very first synthetic "change" that fires from provider-sync so we
  // don't echo the server's own state back to it immediately.
  const skipFirstChange = React.useRef(true);
  React.useEffect(() => {
    const off = editor.onChange(() => {
      if (skipFirstChange.current) {
        skipFirstChange.current = false;
        return;
      }
      scheduleSave();
    });
    return off;
    // `editor` identity is stable across renders per useCreateBlockNote.
  }, [editor, scheduleSave]);

  // Flush on unmount so a navigation away doesn't drop pending edits.
  React.useEffect(() => {
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        saveTimer.current = null;
        void doSave();
      }
    };
  }, [doSave]);

  // Persist displayed entityId on the document root for consumers that
  // want to walk from document → entity quickly. Read-only; the backend
  // owns the canonical mapping.
  React.useEffect(() => {
    if (!entityId) return;
    const meta = ydoc.getMap("meta");
    if (meta.get("entityId") !== entityId) meta.set("entityId", entityId);
  }, [ydoc, entityId]);

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between gap-2 border-b bg-background/80 px-4 py-2 text-xs">
        <div className="flex min-w-0 items-center gap-2">
          <StatusBadge status={status} />
          <span className="truncate font-medium text-foreground" title={title}>
            {title || "Untitled"}
          </span>
        </div>
        <SavedIndicator saving={saving} savedAt={savedAt} error={saveError} />
      </div>

      <div className="relative">
        <BlockNoteView
          editor={editor}
          slashMenu={false}
          theme={editorTheme}
          className="min-h-[60vh] px-2 py-4"
        >
          <SlashMenu editor={editor} />
        </BlockNoteView>
      </div>
    </div>
  );
}

export default Editor;
