"use client";

import { useState } from "react";

import { PropsEditor } from "@/components/entity/PropsEditor";
import { Button } from "@/components/ui/button";
import type { Entity, EntityType } from "@/lib/api/types";

interface EntityFormProps {
  entity: Entity;
  type: EntityType | null;
  onSubmit: (data: {
    canonical: string;
    aliases: string[];
    summary: string | null;
    props: Record<string, unknown>;
  }) => void | Promise<void>;
  submitLabel?: string;
}

export function EntityForm({
  entity,
  type,
  onSubmit,
  submitLabel = "Save",
}: EntityFormProps) {
  const [busy, setBusy] = useState(false);
  const [canonical, setCanonical] = useState(entity.canonical);
  const [aliasesText, setAliasesText] = useState(entity.aliases.join(", "));
  const [summary, setSummary] = useState(entity.summary ?? "");
  const [props, setProps] = useState<Record<string, unknown>>(entity.props);

  const schema = type?.schema ?? {
    type: "object",
    properties: {},
    additionalProperties: true,
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await onSubmit({
        canonical,
        aliases: aliasesText
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        summary: summary || null,
        props,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1">
        <label className="text-sm font-medium">Canonical name</label>
        <input
          required
          value={canonical}
          onChange={(e) => setCanonical(e.target.value)}
          className="flex h-9 w-full rounded-md border bg-transparent px-3 text-sm shadow-sm"
        />
      </div>
      <div className="space-y-1">
        <label className="text-sm font-medium">Aliases (comma-separated)</label>
        <input
          value={aliasesText}
          onChange={(e) => setAliasesText(e.target.value)}
          className="flex h-9 w-full rounded-md border bg-transparent px-3 text-sm shadow-sm"
        />
      </div>
      <div className="space-y-1">
        <label className="text-sm font-medium">Summary</label>
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          rows={3}
          className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm"
        />
      </div>

      <div className="rounded-md border bg-muted/30 p-3">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Properties
        </div>
        <PropsEditor schema={schema} value={props} onChange={setProps} />
      </div>

      <div className="flex justify-end gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
