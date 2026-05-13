"use client";

import { useCallback, useRef, useState } from "react";

import { getToken } from "@/lib/api/client";
import { useWorkspace } from "@/lib/workspace-context";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

interface ToolEvent {
  id: string;
  name: string;
  input: unknown;
  result?: unknown;
  status: "running" | "done";
}

export default function PlaygroundPage() {
  const { workspace } = useWorkspace();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const inflight = useRef<AbortController | null>(null);

  const send = useCallback(async () => {
    if (!workspace || !input.trim() || streaming) return;
    const userTurn: ChatTurn = { role: "user", text: input.trim() };
    const nextTurns = [...turns, userTurn];
    setTurns(nextTurns);
    setInput("");
    setStreaming(true);

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
        body: JSON.stringify({
          messages: nextTurns.map((t) => ({ role: t.role, content: t.text })),
        }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => "");
        setTurns((curr) => [
          ...curr,
          { role: "assistant", text: `Error: ${res.status} ${detail}` },
        ]);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let assistantText = "";
      const assistantIndex = nextTurns.length;
      setTurns((curr) => [...curr, { role: "assistant", text: "" }]);

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
              copy[assistantIndex] = { role: "assistant", text: assistantText };
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
              { role: "assistant", text: `Error: ${evt.detail}` },
            ]);
          }
        }
      }
    } finally {
      setStreaming(false);
      inflight.current = null;
    }
  }, [workspace, input, turns, streaming]);

  const cancel = useCallback(() => {
    inflight.current?.abort();
    inflight.current = null;
    setStreaming(false);
  }, []);

  const clear = useCallback(() => {
    setTurns([]);
    setTools([]);
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">Playground</h1>
          <p className="text-xs text-muted-foreground">
            Watch a real Claude agent stream tool calls against your workspace.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={shareTrace}
            disabled={turns.length === 0}
            className="rounded border px-3 py-1 text-xs disabled:opacity-40"
          >
            Share trace
          </button>
          <button
            type="button"
            onClick={clear}
            disabled={streaming || turns.length === 0}
            className="rounded border px-3 py-1 text-xs disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 md:grid-cols-2">
        <section className="flex min-h-0 flex-col border-r">
          <div className="min-h-0 flex-1 space-y-3 overflow-auto px-6 py-4">
            {turns.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Ask anything. Try: &ldquo;Record that Anthropic was founded in
                2021 by Dario Amodei.&rdquo;
              </p>
            ) : null}
            {turns.map((t, i) => (
              <div
                key={i}
                className={
                  t.role === "user"
                    ? "ml-auto max-w-[85%] rounded-lg bg-foreground/5 px-3 py-2 text-sm"
                    : "max-w-[85%] whitespace-pre-wrap rounded-lg bg-background px-3 py-2 text-sm"
                }
              >
                {t.text || <span className="opacity-50">…</span>}
              </div>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
            className="flex gap-2 border-t p-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Message the agent…"
              disabled={streaming}
              className="flex-1 rounded border px-3 py-2 text-sm"
            />
            {streaming ? (
              <button
                type="button"
                onClick={cancel}
                className="rounded border px-3 py-1 text-xs"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="rounded bg-foreground px-3 py-1 text-xs text-background disabled:opacity-40"
              >
                Send
              </button>
            )}
          </form>
        </section>
        <section className="flex min-h-0 flex-col">
          <h2 className="border-b px-6 py-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Tool calls ({tools.length})
          </h2>
          <div className="min-h-0 flex-1 space-y-3 overflow-auto px-6 py-4">
            {tools.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Tool calls will appear here as the agent runs.
              </p>
            ) : null}
            {tools.map((t) => (
              <details key={t.id} className="rounded border bg-background">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium">
                  <span className="font-mono">{t.name}</span>{" "}
                  <span className="text-muted-foreground">[{t.status}]</span>
                </summary>
                <div className="space-y-2 border-t px-3 py-2 text-xs">
                  <div>
                    <div className="font-medium text-muted-foreground">
                      input
                    </div>
                    <pre className="overflow-auto rounded bg-foreground/5 p-2 text-[11px]">
                      {JSON.stringify(t.input, null, 2)}
                    </pre>
                  </div>
                  {t.result !== undefined ? (
                    <div>
                      <div className="font-medium text-muted-foreground">
                        result
                      </div>
                      <pre className="overflow-auto rounded bg-foreground/5 p-2 text-[11px]">
                        {JSON.stringify(t.result, null, 2)}
                      </pre>
                    </div>
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
