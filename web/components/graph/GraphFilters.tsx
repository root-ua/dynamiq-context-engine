"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  PiCheck as Check,
  PiCaretDown as ChevronDown,
  PiArrowCounterClockwise as RotateCcw,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ontologyApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

import { DEFAULT_FILTERS, type GraphFiltersValue, colorForType } from "./types";

export interface GraphFiltersProps {
  workspaceId: string;
  value: GraphFiltersValue;
  onChange: (value: GraphFiltersValue) => void;
}

export function GraphFilters({
  workspaceId,
  value,
  onChange,
}: GraphFiltersProps) {
  const typesQuery = useQuery({
    queryKey: ["ontology.types", workspaceId],
    queryFn: () => ontologyApi.listTypes(workspaceId),
    enabled: !!workspaceId,
  });

  const relationsQuery = useQuery({
    queryKey: ["ontology.relations", workspaceId],
    queryFn: () => ontologyApi.listRelations(workspaceId),
    enabled: !!workspaceId,
  });

  const toggleList = React.useCallback(
    (key: "types" | "predicates", slug: string) => {
      const list = value[key];
      const next = list.includes(slug)
        ? list.filter((s) => s !== slug)
        : [...list, slug];
      onChange({ ...value, [key]: next });
    },
    [value, onChange],
  );

  const reset = React.useCallback(() => onChange(DEFAULT_FILTERS), [onChange]);

  const isDirty =
    value.types.length > 0 ||
    value.predicates.length > 0 ||
    value.direction !== DEFAULT_FILTERS.direction ||
    value.maxHops !== DEFAULT_FILTERS.maxHops ||
    value.asOf !== null;

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="text-sm font-semibold">Filters</div>
        {isDirty && (
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            className="h-7 gap-1 px-2 text-xs"
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </Button>
        )}
      </div>

      <Accordion title="Entity types" count={value.types.length} defaultOpen>
        {typesQuery.isLoading && <Placeholder text="Loading types…" />}
        {typesQuery.data?.length === 0 && (
          <Placeholder text="No entity types defined." />
        )}
        <div className="space-y-1">
          {typesQuery.data?.map((t) => {
            const active = value.types.includes(t.slug);
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => toggleList("types", t.slug)}
                aria-pressed={active}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  active ? "bg-accent" : "hover:bg-accent/60",
                )}
              >
                <span className="flex items-center gap-2 truncate">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: colorForType(t.slug) }}
                  />
                  <span className="truncate">{t.name}</span>
                </span>
                {active && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            );
          })}
        </div>
      </Accordion>

      <Accordion title="Relations" count={value.predicates.length}>
        {relationsQuery.isLoading && <Placeholder text="Loading relations…" />}
        {relationsQuery.data?.length === 0 && (
          <Placeholder text="No relations defined." />
        )}
        <div className="space-y-1">
          {relationsQuery.data?.map((r) => {
            const active = value.predicates.includes(r.slug);
            return (
              <button
                key={r.id}
                type="button"
                onClick={() => toggleList("predicates", r.slug)}
                aria-pressed={active}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  active ? "bg-accent" : "hover:bg-accent/60",
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-mono text-xs">{r.slug}</span>
                  {r.temporal && <Badge variant="secondary">temporal</Badge>}
                </span>
                {active && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            );
          })}
        </div>
      </Accordion>

      <Accordion title="Direction" compact>
        <Select
          value={value.direction}
          onChange={(e) =>
            onChange({
              ...value,
              direction: e.target.value as GraphFiltersValue["direction"],
            })
          }
        >
          <option value="both">Both directions</option>
          <option value="out">Outgoing</option>
          <option value="in">Incoming</option>
        </Select>
      </Accordion>

      <Accordion title={`Max hops (${value.maxHops})`} compact>
        <input
          type="range"
          min={1}
          max={4}
          step={1}
          value={value.maxHops}
          onChange={(e) =>
            onChange({ ...value, maxHops: Number(e.target.value) })
          }
          className="w-full accent-primary"
        />
        <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
          <span>1</span>
          <span>2</span>
          <span>3</span>
          <span>4</span>
        </div>
      </Accordion>

      <Accordion title="As of" compact>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Use current time
            </span>
            <Switch
              checked={value.asOf === null}
              onChange={(e) =>
                onChange({
                  ...value,
                  asOf: e.target.checked ? null : new Date().toISOString(),
                })
              }
            />
          </div>
          <Input
            type="datetime-local"
            value={isoToLocalInput(value.asOf)}
            disabled={value.asOf === null}
            onChange={(e) =>
              onChange({ ...value, asOf: localInputToIso(e.target.value) })
            }
          />
        </div>
      </Accordion>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local primitives
// ---------------------------------------------------------------------------

function Accordion({
  title,
  count,
  defaultOpen = false,
  compact = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  compact?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="border-b">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-accent/50"
      >
        <span className="flex items-center gap-2">
          {title}
          {count != null && count > 0 && (
            <Badge variant="secondary" className="h-4 text-[10px]">
              {count}
            </Badge>
          )}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div
          className={cn(
            "px-4",
            compact ? "pb-3" : "max-h-56 overflow-y-auto pb-3",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return <div className="py-2 text-xs text-muted-foreground">{text}</div>;
}

/** ISO instant → local `datetime-local` string (user timezone). */
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Local `datetime-local` input → ISO instant. */
function localInputToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
