"use client";

import type { WidgetProps } from "@rjsf/utils";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  PiSpinnerGap as Loader2,
  PiMagnifyingGlass as Search,
  PiX as X,
} from "react-icons/pi";

import { EntityPicker } from "@/components/editor/EntityPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { entitiesApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

/**
 * rjsf widget that renders an entity reference: stores the entity's UUID
 * (or IRI / canonical name) in the form, but lets the user pick from the
 * workspace's entities via the shared EntityPicker. Shows the resolved
 * canonical name next to the input so the user sees what they picked.
 */
export function EntityRefWidget(props: WidgetProps) {
  const {
    id,
    value,
    onChange,
    required,
    disabled,
    readonly,
    label,
    placeholder,
  } = props;
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? null;
  const [pickerOpen, setPickerOpen] = useState(false);

  const resolved = useQuery({
    queryKey: ["entity-ref", wsId, value],
    queryFn: () => {
      if (!wsId || !value) throw new Error("no ref");
      return entitiesApi.get(wsId, String(value));
    },
    enabled: !!wsId && typeof value === "string" && value.length > 0,
    staleTime: 30_000,
    retry: false,
  });

  return (
    <>
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            id={id}
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value || undefined)}
            placeholder={
              placeholder ||
              (label
                ? `${label} — id, IRI, or name`
                : "entity id, IRI, or name")
            }
            required={required}
            disabled={disabled || readonly}
            className="pl-8"
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setPickerOpen(true)}
          disabled={!wsId || disabled || readonly}
        >
          Pick…
        </Button>
        {value && !disabled && !readonly && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onChange(undefined)}
            title="Clear"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {value && (
        <div className="mt-1 flex items-center gap-2 text-xs">
          {resolved.isLoading && (
            <span className="flex items-center gap-1 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> resolving…
            </span>
          )}
          {resolved.data && (
            <>
              <Badge variant="secondary">{resolved.data.type_slug}</Badge>
              <span className="font-medium">{resolved.data.canonical}</span>
              {resolved.data.iri && (
                <span className="text-muted-foreground">
                  {resolved.data.iri}
                </span>
              )}
            </>
          )}
          {resolved.isError && (
            <span className="text-destructive">
              Couldn't resolve — double-check the id / name.
            </span>
          )}
        </div>
      )}

      <EntityPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onPick={(entity) => onChange(entity.id)}
      />
    </>
  );
}
