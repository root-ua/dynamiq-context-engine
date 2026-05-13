"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface JsonViewProps {
  value: unknown;
  initialCollapseDepth?: number;
  className?: string;
}

/**
 * Small, dependency-free JSON renderer with collapsibles, syntax
 * coloring, and copy buttons. Keeps the bundle slim — heavier libs
 * like react-json-view aren't worth the weight for the playground.
 */
export function JsonView({
  value,
  initialCollapseDepth = 2,
  className,
}: JsonViewProps) {
  return (
    <div
      className={cn(
        "overflow-x-auto rounded-md bg-muted/30 p-3 font-mono text-[11px] leading-relaxed",
        className,
      )}
    >
      <Node value={value} depth={0} collapseAt={initialCollapseDepth} />
    </div>
  );
}

function Node({
  value,
  depth,
  collapseAt,
}: {
  value: unknown;
  depth: number;
  collapseAt: number;
}) {
  if (value === null) {
    return <span className="text-muted-foreground">null</span>;
  }
  if (value === undefined) {
    return <span className="text-muted-foreground">undefined</span>;
  }
  if (typeof value === "string") {
    return <Str text={value} />;
  }
  if (typeof value === "number" || typeof value === "bigint") {
    return (
      <span className="text-amber-700 dark:text-amber-300">
        {String(value)}
      </span>
    );
  }
  if (typeof value === "boolean") {
    return (
      <span className="text-purple-700 dark:text-purple-300">
        {String(value)}
      </span>
    );
  }
  if (Array.isArray(value)) {
    return (
      <Coll items={value} depth={depth} collapseAt={collapseAt} bracket="[]" />
    );
  }
  if (typeof value === "object") {
    return (
      <Coll
        items={Object.entries(value as Record<string, unknown>)}
        depth={depth}
        collapseAt={collapseAt}
        bracket="{}"
      />
    );
  }
  // Fall-through for any other primitive (symbol, function). Render as
  // a literal to satisfy lint without `Object.prototype.toString`.
  return <span>{typeof value}</span>;
}

function Str({ text }: { text: string }) {
  // Truncate very long strings inline; the user can click to expand.
  const TRUNC_AT = 240;
  const [expanded, setExpanded] = React.useState(false);
  if (text.length <= TRUNC_AT) {
    return (
      <span className="text-emerald-700 dark:text-emerald-300">
        &quot;{text}&quot;
      </span>
    );
  }
  return (
    <span className="text-emerald-700 dark:text-emerald-300">
      &quot;{expanded ? text : text.slice(0, TRUNC_AT) + "…"}&quot;{" "}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="ml-1 rounded border px-1.5 text-[10px] font-normal text-muted-foreground hover:bg-accent"
      >
        {expanded ? "collapse" : "show all"}
      </button>
    </span>
  );
}

function Coll({
  items,
  depth,
  collapseAt,
  bracket,
}: {
  items: unknown[] | [string, unknown][];
  depth: number;
  collapseAt: number;
  bracket: "[]" | "{}";
}) {
  const [open, setOpen] = React.useState(depth < collapseAt);
  const [openBr, closeBr] = bracket.split("");
  const isObject = bracket === "{}";

  if (items.length === 0) {
    return (
      <span>
        {openBr}
        {closeBr}
      </span>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded text-muted-foreground hover:text-foreground"
      >
        {openBr}
        <span className="px-1 text-[10px]">{items.length}</span>
        {closeBr}
      </button>
    );
  }

  return (
    <span>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="text-muted-foreground hover:text-foreground"
      >
        {openBr}
      </button>
      <div className="ml-3 border-l border-border/40 pl-2">
        {items.map((entry, i) => {
          const isLast = i === items.length - 1;
          if (isObject) {
            const [k, v] = entry as [string, unknown];
            return (
              <div key={k}>
                <span className="text-sky-700 dark:text-sky-300">
                  &quot;{k}&quot;
                </span>
                <span className="text-muted-foreground">: </span>
                <Node value={v} depth={depth + 1} collapseAt={collapseAt} />
                {!isLast && <span className="text-muted-foreground">,</span>}
              </div>
            );
          }
          return (
            <div key={i}>
              <Node value={entry} depth={depth + 1} collapseAt={collapseAt} />
              {!isLast && <span className="text-muted-foreground">,</span>}
            </div>
          );
        })}
      </div>
      <span className="text-muted-foreground">{closeBr}</span>
    </span>
  );
}
