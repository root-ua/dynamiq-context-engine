"use client";

import type { WidgetProps } from "@rjsf/utils";
import { useQuery } from "@tanstack/react-query";

import { Select } from "@/components/ui/select";
import { ontologyApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

/** rjsf widget for relation slugs: dropdown of all live relation types. */
export function RelationRefWidget(props: WidgetProps) {
  const { id, value, onChange, required, disabled, readonly } = props;
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? null;

  const relations = useQuery({
    queryKey: ["ontology", wsId, "relations"],
    queryFn: () => ontologyApi.listRelations(wsId!),
    enabled: !!wsId,
    staleTime: 60_000,
  });

  return (
    <Select
      id={id}
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value || undefined)}
      required={required}
      disabled={disabled || readonly || !wsId}
    >
      <option value="">Pick a relation…</option>
      {(relations.data ?? []).map((r) => (
        <option key={r.id} value={r.slug}>
          {r.name} ({r.slug})
        </option>
      ))}
    </Select>
  );
}
