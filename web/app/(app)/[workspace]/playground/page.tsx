"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  PiChatsCircle,
  PiFile,
  PiFileText,
  PiImageSquare,
  PiPaperclip,
  PiStopCircle,
} from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { EmptyState } from "@/components/ui/empty";
import { JsonView } from "@/components/ui/json-view";
import { getToken } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/workspace-context";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// File handoff to Claude. The backend forwards content blocks straight
// to Anthropic's API; the platform does not parse PDFs / images itself
// (Phase R guardrail — ingestion is the agent's job).
const MAX_FILE_BYTES = 32 * 1024 * 1024; // 32 MB — Anthropic's PDF cap.

interface AttachedFile {
  name: string;
  mimeType: string;
  base64: string;
  kind: "document" | "image";
  bytes: number;
}

type TurnContent =
  | { kind: "text"; text: string; attachments?: AttachedFile[] }
  | { kind: "system"; text: string };

interface ChatTurn {
  role: "user" | "assistant" | "system";
  content: TurnContent;
}

interface ToolEvent {
  id: string;
  name: string;
  input: unknown;
  result?: unknown;
  status: "running" | "done";
}

const SUGGESTIONS = [
  "What's in this workspace?",
  "Use get_fact to look up Anthropic's founding year.",
  "Summarize the document I just dropped and record the key facts.",
];

function classifyFile(file: File): "document" | "image" | "text" | null {
  const mime = file.type || "";
  const name = file.name.toLowerCase();
  if (mime === "application/pdf" || name.endsWith(".pdf")) {
    return "document";
  }
  if (mime.startsWith("image/")) return "image";
  if (
    mime.startsWith("text/") ||
    name.endsWith(".txt") ||
    name.endsWith(".md") ||
    name.endsWith(".mdx") ||
    name.endsWith(".markdown") ||
    name.endsWith(".json") ||
    name.endsWith(".csv")
  ) {
    return "text";
  }
  return null;
}

async function toBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  let bin = "";
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

export default function PlaygroundPage() {
  const { workspace } = useWorkspace();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [pending, setPending] = useState<AttachedFile[]>([]);
  const [dropping, setDropping] = useState(false);
  const [pickedFiles, setPickedFiles] = useState(0);
  const [paneTab, setPaneTab] = useState<"chat" | "trace">("chat");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const inflight = useRef<AbortController | null>(null);

  const traceCount = tools.length;

  const ingestFiles = useCallback(async (files: FileList | File[]) => {
    const accepted: AttachedFile[] = [];
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      const kind = classifyFile(file);
      if (!kind) {
        rejected.push(`${file.name} (unsupported type)`);
        continue;
      }
      if (file.size > MAX_FILE_BYTES) {
        rejected.push(`${file.name} (over ${MAX_FILE_BYTES / 1024 / 1024} MB)`);
        continue;
      }
      if (kind === "text") {
        // Inline text files directly into the message so Claude doesn't
        // need to decode them.
        const text = await file.text();
        accepted.push({
          name: file.name,
          mimeType: file.type || "text/plain",
          base64: btoa(unescape(encodeURIComponent(text))),
          kind: "document",
          bytes: file.size,
        });
        continue;
      }
      accepted.push({
        name: file.name,
        mimeType:
          file.type || (kind === "document" ? "application/pdf" : "image/png"),
        base64: await toBase64(file),
        kind,
        bytes: file.size,
      });
    }
    if (rejected.length) {
      setTurns((curr) => [
        ...curr,
        {
          role: "system",
          content: {
            kind: "system",
            text: `Skipped: ${rejected.join(", ")}`,
          },
        },
      ]);
    }
    setPending((curr) => [...curr, ...accepted]);
    setPickedFiles((n) => n + accepted.length);
  }, []);

  const onDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setDropping(false);
      if (!e.dataTransfer?.files?.length) return;
      await ingestFiles(e.dataTransfer.files);
    },
    [ingestFiles],
  );

  const send = useCallback(async () => {
    if (!workspace || streaming) return;
    if (!input.trim() && pending.length === 0) return;

    const attached = pending;
    const text = input.trim();
    const userTurn: ChatTurn = {
      role: "user",
      content: { kind: "text", text, attachments: attached },
    };
    const nextTurns = [...turns, userTurn];
    setTurns(nextTurns);
    setInput("");
    setPending([]);
    setStreaming(true);
    setPaneTab("chat");

    // Build the API payload: history of turns mapped to Anthropic-shape
    // content blocks. The backend passes blocks straight to Claude.
    const apiMessages = nextTurns
      .filter((t) => t.role !== "system")
      .map((t) => {
        if (t.content.kind === "system") return null;
        const blocks: Array<Record<string, unknown>> = [];
        for (const att of t.content.attachments ?? []) {
          if (att.kind === "image") {
            blocks.push({
              type: "image",
              source: {
                type: "base64",
                media_type: att.mimeType,
                data: att.base64,
              },
            });
          } else {
            blocks.push({
              type: "document",
              source: {
                type: "base64",
                media_type: att.mimeType,
                data: att.base64,
              },
              title: att.name,
            });
          }
        }
        if (t.content.text || blocks.length === 0) {
          blocks.push({ type: "text", text: t.content.text || "" });
        }
        return {
          role: t.role,
          content:
            blocks.length === 1 && blocks[0]!.type === "text"
              ? (blocks[0] as { text: string }).text
              : blocks,
        };
      })
      .filter(Boolean);

    const controller = new AbortController();
    inflight.current = controller;
    try {
      const token = await getToken(workspace.id);
      const res = await fetch(`${API_URL}/api/playground/chat`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-Workspace-Id": workspace.id,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify({ messages: apiMessages }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => "");
        setTurns((curr) => [
          ...curr,
          {
            role: "assistant",
            content: {
              kind: "text",
              text: `Error: ${res.status} ${detail}`,
            },
          },
        ]);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let assistantText = "";
      const assistantIndex = nextTurns.length;
      setTurns((curr) => [
        ...curr,
        { role: "assistant", content: { kind: "text", text: "" } },
      ]);

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const raw of lines) {
          const line = raw.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let evt: { type: string; [k: string]: unknown };
          try {
            evt = JSON.parse(payload);
          } catch {
            continue;
          }
          if (evt.type === "text_delta" && typeof evt.text === "string") {
            assistantText = evt.text;
            setTurns((curr) => {
              const copy = [...curr];
              copy[assistantIndex] = {
                role: "assistant",
                content: { kind: "text", text: assistantText },
              };
              return copy;
            });
          } else if (evt.type === "tool_call") {
            setTools((curr) => [
              ...curr,
              {
                id: String(evt.id),
                name: String(evt.name),
                input: evt.input,
                status: "running",
              },
            ]);
          } else if (evt.type === "tool_result") {
            setTools((curr) =>
              curr.map((t) =>
                t.id === evt.tool_use_id
                  ? { ...t, result: evt.content, status: "done" }
                  : t,
              ),
            );
          } else if (evt.type === "error" && typeof evt.detail === "string") {
            setTurns((curr) => [
              ...curr,
              {
                role: "assistant",
                content: { kind: "text", text: `Error: ${evt.detail}` },
              },
            ]);
          }
        }
      }
    } finally {
      setStreaming(false);
      inflight.current = null;
    }
  }, [workspace, input, pending, turns, streaming]);

  const cancel = useCallback(() => {
    inflight.current?.abort();
    inflight.current = null;
    setStreaming(false);
  }, []);

  const clear = useCallback(() => {
    setTurns([]);
    setTools([]);
    setPending([]);
  }, []);

  const shareTrace = useCallback(() => {
    const blob = new Blob([JSON.stringify({ turns, tools }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `playground-trace-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [turns, tools]);

  const isEmpty = turns.length === 0;
  const formattedSize = useMemo(
    () => (n: number) => `${(n / 1024).toFixed(1)} KB`,
    [],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">Playground</h1>
          <p className="text-xs text-muted-foreground">
            Watch a real Claude agent stream tool calls against your workspace.
            Drop a PDF, image, or text file to hand it to Claude — Claude reads
            it natively and calls{" "}
            <code className="rounded bg-muted px-1">add_episode</code> to land
            facts.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={shareTrace}
            disabled={isEmpty}
          >
            Share trace
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={clear}
            disabled={streaming || isEmpty}
          >
            Clear
          </Button>
        </div>
      </header>

      {/* Mobile tab toggle */}
      <div className="flex border-b md:hidden">
        <button
          type="button"
          onClick={() => setPaneTab("chat")}
          className={cn(
            "flex-1 py-2 text-xs",
            paneTab === "chat" && "border-b-2 border-foreground font-medium",
          )}
        >
          Chat
        </button>
        <button
          type="button"
          onClick={() => setPaneTab("trace")}
          className={cn(
            "flex-1 py-2 text-xs",
            paneTab === "trace" && "border-b-2 border-foreground font-medium",
          )}
        >
          Tool calls ({traceCount})
        </button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 md:grid-cols-2">
        {/* Chat pane */}
        <section
          className={cn(
            "flex min-h-0 flex-col border-r",
            paneTab === "chat" ? "" : "hidden md:flex",
          )}
          onDragOver={(e) => {
            e.preventDefault();
            setDropping(true);
          }}
          onDragLeave={() => setDropping(false)}
          onDrop={onDrop}
        >
          <div
            className={cn(
              "min-h-0 flex-1 space-y-3 overflow-auto px-6 py-4",
              dropping &&
                "outline-dashed outline-2 outline-offset-[-8px] outline-primary/40",
            )}
          >
            {isEmpty ? (
              <div className="py-6">
                <EmptyState
                  icon={PiChatsCircle}
                  title="Drop a file or ask anything"
                  description="Claude has access to 22 MCP tools against this workspace. Try one of these, or drag a PDF / image / .md file anywhere in this pane."
                />
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setInput(s)}
                      className="rounded-full border px-3 py-1 text-xs hover:bg-accent"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {turns.map((t, i) => {
              if (t.content.kind === "system") {
                return (
                  <div
                    key={i}
                    className="mx-auto max-w-[85%] rounded-md border border-dashed bg-muted/20 px-3 py-1.5 text-center text-xs text-muted-foreground"
                  >
                    {t.content.text}
                  </div>
                );
              }
              const isUser = t.role === "user";
              const atts = t.content.attachments ?? [];
              return (
                <div
                  key={i}
                  className={cn(
                    "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                    isUser
                      ? "ml-auto bg-foreground/5"
                      : "whitespace-pre-wrap bg-background",
                  )}
                >
                  {atts.length > 0 && (
                    <div className="mb-2 flex flex-col gap-1.5">
                      {atts.map((a, j) => (
                        <div
                          key={j}
                          className="flex items-center gap-2 rounded-md border bg-background px-2 py-1 text-xs"
                        >
                          {a.kind === "image" ? (
                            <PiImageSquare className="size-4 text-muted-foreground" />
                          ) : a.mimeType === "application/pdf" ? (
                            <PiFileText className="size-4 text-muted-foreground" />
                          ) : (
                            <PiFile className="size-4 text-muted-foreground" />
                          )}
                          <span className="truncate">{a.name}</span>
                          <span className="ml-auto text-muted-foreground">
                            {formattedSize(a.bytes)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {t.content.text ? (
                    t.content.text
                  ) : isUser ? null : streaming && i === turns.length - 1 ? (
                    <span className="inline-flex gap-1">
                      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
                      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground delay-75" />
                      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground delay-150" />
                    </span>
                  ) : (
                    <span className="opacity-50">…</span>
                  )}
                </div>
              );
            })}
          </div>

          {/* Pending attachments */}
          {pending.length > 0 && (
            <div className="flex flex-wrap gap-1.5 border-t bg-muted/20 px-3 py-2 text-xs">
              {pending.map((a, j) => (
                <span
                  key={`${a.name}-${j}`}
                  className="inline-flex items-center gap-1 rounded-md border bg-background px-2 py-0.5"
                >
                  {a.kind === "image" ? (
                    <PiImageSquare className="size-3.5" />
                  ) : (
                    <PiFileText className="size-3.5" />
                  )}
                  {a.name}
                  <button
                    type="button"
                    onClick={() =>
                      setPending((curr) => curr.filter((_, k) => k !== j))
                    }
                    className="ml-1 text-muted-foreground hover:text-foreground"
                    aria-label={`Remove ${a.name}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* Input row */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
            className="flex gap-2 border-t p-3"
          >
            <input
              ref={fileInputRef}
              type="file"
              hidden
              multiple
              accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.md,.mdx,.markdown,.json,.csv,application/pdf,image/*,text/plain,text/markdown"
              onChange={(e) => {
                if (e.target.files) {
                  void ingestFiles(e.target.files);
                  e.target.value = ""; // allow re-selecting the same file
                }
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="rounded-md border px-2 py-2 text-muted-foreground hover:bg-accent"
              aria-label="Attach file"
            >
              <PiPaperclip className="size-4" />
            </button>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                pending.length > 0
                  ? `Send ${pending.length} file${pending.length === 1 ? "" : "s"} with a message…`
                  : "Message the agent…"
              }
              disabled={streaming}
              className="flex-1 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            {streaming ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={cancel}
              >
                <PiStopCircle className="size-4" />
                Stop
              </Button>
            ) : (
              <Button
                type="submit"
                size="sm"
                disabled={!input.trim() && pending.length === 0}
              >
                Send
              </Button>
            )}
          </form>
          {pickedFiles > 0 && (
            <p className="border-t bg-muted/10 px-4 py-1 text-[11px] text-muted-foreground">
              {pickedFiles} file{pickedFiles === 1 ? "" : "s"} attached so far.
              Claude reads them natively (Anthropic API supports PDFs + images)
              and decides which facts to record.
            </p>
          )}
        </section>

        {/* Trace pane */}
        <section
          className={cn(
            "flex min-h-0 flex-col",
            paneTab === "trace" ? "" : "hidden md:flex",
          )}
        >
          <h2 className="border-b px-6 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Tool calls ({traceCount})
          </h2>
          <div className="min-h-0 flex-1 space-y-3 overflow-auto px-6 py-4">
            {tools.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Tool calls will appear here as the agent runs.
              </p>
            ) : null}
            {tools.map((t) => (
              <details
                key={t.id}
                open
                className="rounded-md border bg-background"
              >
                <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-xs">
                  <span className="font-mono">{t.name}</span>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[10px]",
                      t.status === "running"
                        ? "bg-amber-500/10 text-amber-600 dark:text-amber-300"
                        : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
                    )}
                  >
                    {t.status}
                  </span>
                </summary>
                <div className="space-y-2 border-t px-3 py-2 text-xs">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-muted-foreground">
                      input
                    </div>
                    <CopyButton
                      value={JSON.stringify(t.input, null, 2)}
                      label=""
                    />
                  </div>
                  <JsonView value={t.input} />
                  {t.result !== undefined ? (
                    <>
                      <div className="flex items-center justify-between pt-1">
                        <div className="font-medium text-muted-foreground">
                          result
                        </div>
                        <CopyButton
                          value={JSON.stringify(t.result, null, 2)}
                          label=""
                        />
                      </div>
                      <JsonView value={t.result} />
                    </>
                  ) : null}
                </div>
              </details>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
