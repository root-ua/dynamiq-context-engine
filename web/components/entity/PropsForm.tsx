"use client";

import * as React from "react";

import { PropsEditor } from "@/components/entity/PropsEditor";

type SchemaLike = Record<string, unknown>;

interface PropsFormProps {
  schema: SchemaLike | null | undefined;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  disabled?: boolean;
  debounceMs?: number;
  emptyState?: React.ReactNode;
}

/**
 * Debounced props editor. Used inline on screens where we want autosave
 * rather than an explicit Save button (the document editor sidebar,
 * chiefly).
 *
 * Delegates rendering to `PropsEditor` — a hand-rolled Tailwind-styled
 * form that replaces the previous `@rjsf/core` form, which was
 * rendering additional properties as run-on labels/values without any
 * of Bootstrap's spacing.
 */
export function PropsForm({
  schema,
  value,
  onChange,
  disabled = false,
  debounceMs = 800,
  emptyState,
}: PropsFormProps) {
  // Local draft so rapid edits don't round-trip through the parent.
  const [draft, setDraft] = React.useState(value);
  const lastExternal = React.useRef(value);

  React.useEffect(() => {
    if (value !== lastExternal.current) {
      lastExternal.current = value;
      setDraft(value);
    }
  }, [value]);

  const flushTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = React.useRef<Record<string, unknown> | null>(null);

  React.useEffect(
    () => () => {
      if (flushTimer.current) clearTimeout(flushTimer.current);
    },
    [],
  );

  const hasProperties =
    !!schema &&
    typeof schema === "object" &&
    Object.keys(
      (schema as { properties?: Record<string, unknown> }).properties ?? {},
    ).length > 0;

  if (!hasProperties) {
    return (
      <div className="text-xs text-muted-foreground">
        {emptyState ?? "No extra fields for this type."}
      </div>
    );
  }

  function handleChange(next: Record<string, unknown>): void {
    setDraft(next);
    pending.current = next;
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = setTimeout(() => {
      flushTimer.current = null;
      if (pending.current) {
        lastExternal.current = pending.current;
        onChange(pending.current);
        pending.current = null;
      }
    }, debounceMs);
  }

  return (
    <PropsEditor
      schema={schema}
      value={draft}
      onChange={handleChange}
      disabled={disabled}
    />
  );
}
