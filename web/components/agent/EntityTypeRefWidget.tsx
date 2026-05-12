"use client";

import type { WidgetProps } from "@rjsf/utils";
import { useQuery } from "@tanstack/react-query";

import { Select } from "@/components/ui/select";
import { ontologyApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

/** rjsf widget for entity-type slugs. */
export function EntityTypeRefWidget(props: WidgetProps) {
  const { id, value, onChange, required, disabled, readonly } = props;
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? null;

  const types = useQuery({
    queryKey: ["ontology", wsId, "types"],
    queryFn: () => ontologyApi.listTypes(wsId!),
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
      <option value="">Any type…</option>
      {(types.data ?? []).map((t) => (
        <option key={t.id} value={t.slug}>
          {t.name} ({t.slug}){" "}
          {t.ui_hints && (t.ui_hints as { abstract?: boolean }).abstract
            ? "· abstract"
            : ""}
        </option>
      ))}
    </Select>
  );
}
