"use client";
import * as React from "react";
import { PiPlus as Plus, PiTrash as Trash } from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export type PropertyType =
  | "string"
  | "number"
  | "integer"
  | "boolean"
  | "date"
  | "date-time"
  | "enum";

export interface SchemaProperty {
  name: string;
  label: string;
  type: PropertyType;
  enumValues: string[];
  required: boolean;
}

interface SchemaEditorProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  disabled?: boolean;
  className?: string;
}

export function SchemaEditor({
  value,
  onChange,
  disabled,
  className,
}: SchemaEditorProps) {
  const [rawText, setRawText] = React.useState(() =>
    JSON.stringify(value ?? {}, null, 2),
  );
  const [rawError, setRawError] = React.useState<string | null>(null);
  const [lastEmitted, setLastEmitted] = React.useState(() =>
    JSON.stringify(value ?? {}),
  );

  // When the parent pushes a new schema (e.g. after save), re-sync the textarea.
  React.useEffect(() => {
    const serialized = JSON.stringify(value ?? {});
    if (serialized !== lastEmitted) {
      setRawText(JSON.stringify(value ?? {}, null, 2));
      setLastEmitted(serialized);
      setRawError(null);
    }
  }, [value, lastEmitted]);

  const properties = React.useMemo(() => parseProperties(value), [value]);

  const emit = (next: Record<string, unknown>) => {
    const serialized = JSON.stringify(next);
    setLastEmitted(serialized);
    setRawText(JSON.stringify(next, null, 2));
    setRawError(null);
    onChange(next);
  };

  const onRawChange = (text: string) => {
    setRawText(text);
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (
        typeof parsed !== "object" ||
        Array.isArray(parsed) ||
        parsed === null
      ) {
        setRawError("Schema must be a JSON object");
        return;
      }
      setRawError(null);
      setLastEmitted(JSON.stringify(parsed));
      onChange(parsed);
    } catch (e) {
      setRawError((e as Error).message);
    }
  };

  const updateProperties = (next: SchemaProperty[]) => {
    emit(serializeProperties(next, value));
  };

  const addProperty = () => {
    const base = "new_field";
    let candidate = base;
    let n = 1;
    while (properties.some((p) => p.name === candidate)) {
      candidate = `${base}_${n++}`;
    }
    updateProperties([
      ...properties,
      {
        name: candidate,
        label: "New field",
        type: "string",
        enumValues: [],
        required: false,
      },
    ]);
  };

  return (
    <div className={cn("space-y-4", className)}>
      <Tabs defaultValue="builder" className="w-full">
        <TabsList>
          <TabsTrigger value="builder">Builder</TabsTrigger>
          <TabsTrigger value="json">JSON</TabsTrigger>
        </TabsList>

        <TabsContent value="builder" className="space-y-3">
          {properties.length === 0 && (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              No properties yet. Click &ldquo;Add property&rdquo; to define
              fields.
            </div>
          )}

          <div className="space-y-3">
            {properties.map((prop, idx) => (
              <PropertyRow
                key={idx}
                value={prop}
                disabled={disabled}
                onChange={(next) => {
                  const copy = [...properties];
                  copy[idx] = next;
                  updateProperties(copy);
                }}
                onRemove={() => {
                  const copy = properties.filter((_, i) => i !== idx);
                  updateProperties(copy);
                }}
              />
            ))}
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addProperty}
            disabled={disabled}
          >
            <Plus /> Add property
          </Button>
        </TabsContent>

        <TabsContent value="json" className="space-y-2">
          <Label
            htmlFor="schema-raw"
            className="text-xs uppercase tracking-wide text-muted-foreground"
          >
            JSON Schema
          </Label>
          <Textarea
            id="schema-raw"
            value={rawText}
            disabled={disabled}
            onChange={(e) => onRawChange(e.target.value)}
            className="min-h-[280px] font-mono text-xs"
            spellCheck={false}
          />
          {rawError && (
            <p className="text-xs text-destructive">Invalid JSON: {rawError}</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function PropertyRow({
  value,
  onChange,
  onRemove,
  disabled,
}: {
  value: SchemaProperty;
  onChange: (next: SchemaProperty) => void;
  onRemove: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_160px_auto]">
        <div className="space-y-1">
          <Label className="text-xs">Name</Label>
          <Input
            value={value.name}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Label</Label>
          <Input
            value={value.label}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, label: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Type</Label>
          <Select
            value={value.type}
            disabled={disabled}
            onChange={(e) =>
              onChange({ ...value, type: e.target.value as PropertyType })
            }
          >
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="integer">integer</option>
            <option value="boolean">boolean</option>
            <option value="date">date</option>
            <option value="date-time">date-time</option>
            <option value="enum">enum</option>
          </Select>
        </div>
        <div className="flex items-end justify-end">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onRemove}
            disabled={disabled}
            aria-label="Remove property"
          >
            <Trash className="text-destructive" />
          </Button>
        </div>
      </div>

      {value.type === "enum" && (
        <div className="mt-3 space-y-1">
          <Label className="text-xs">Enum values (comma-separated)</Label>
          <Input
            value={value.enumValues.join(", ")}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                ...value,
                enumValues: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 text-xs">
        <Switch
          checked={value.required}
          disabled={disabled}
          onChange={(e) => onChange({ ...value, required: e.target.checked })}
        />
        <span className="text-muted-foreground">Required</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Parse / serialize helpers
// ---------------------------------------------------------------------------

function parseProperties(
  schema: Record<string, unknown> | null | undefined,
): SchemaProperty[] {
  if (!schema || typeof schema !== "object") return [];
  const props = (schema as { properties?: Record<string, unknown> }).properties;
  const required = (schema as { required?: string[] }).required ?? [];
  if (!props || typeof props !== "object") return [];

  return Object.entries(props).map(([name, value]) => {
    const v = (value ?? {}) as Record<string, unknown>;
    const { type, enumValues } = decodeType(v);
    return {
      name,
      label: (v.title as string) ?? name,
      type,
      enumValues,
      required: required.includes(name),
    };
  });
}

function decodeType(prop: Record<string, unknown>): {
  type: PropertyType;
  enumValues: string[];
} {
  if (Array.isArray(prop.enum)) {
    return { type: "enum", enumValues: (prop.enum as unknown[]).map(String) };
  }
  const baseType = (prop.type as string) ?? "string";
  const format = prop.format as string | undefined;
  if (baseType === "string" && format === "date")
    return { type: "date", enumValues: [] };
  if (baseType === "string" && format === "date-time")
    return { type: "date-time", enumValues: [] };
  if (baseType === "integer") return { type: "integer", enumValues: [] };
  if (baseType === "number") return { type: "number", enumValues: [] };
  if (baseType === "boolean") return { type: "boolean", enumValues: [] };
  return { type: "string", enumValues: [] };
}

function serializeProperties(
  properties: SchemaProperty[],
  previous: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const base: Record<string, unknown> = { ...(previous ?? {}) };
  const props: Record<string, unknown> = {};
  const required: string[] = [];

  for (const p of properties) {
    if (!p.name) continue;
    const entry: Record<string, unknown> = { title: p.label || p.name };
    switch (p.type) {
      case "enum":
        entry.type = "string";
        entry.enum = p.enumValues;
        break;
      case "date":
        entry.type = "string";
        entry.format = "date";
        break;
      case "date-time":
        entry.type = "string";
        entry.format = "date-time";
        break;
      case "integer":
        entry.type = "integer";
        break;
      case "number":
        entry.type = "number";
        break;
      case "boolean":
        entry.type = "boolean";
        break;
      default:
        entry.type = "string";
    }
    props[p.name] = entry;
    if (p.required) required.push(p.name);
  }

  base.type = "object";
  base.properties = props;
  if (required.length > 0) {
    base.required = required;
  } else {
    delete base.required;
  }
  return base;
}
