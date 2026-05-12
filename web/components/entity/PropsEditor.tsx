"use client";

import * as React from "react";
import { PiTrash, PiPlus } from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

/**
 * A minimal, Tailwind-styled alternative to `@rjsf/core` for the narrow
 * kind of JSON Schemas we use on entity/document props:
 *
 *  - Top-level object
 *  - String properties (optional `format: email|date|date-time|uri`,
 *    optional `enum`, optional `title`)
 *  - Number / integer properties
 *  - Boolean properties
 *  - `additionalProperties: true` opens a free-form key/value editor
 *    beneath the declared fields
 *
 * Everything else is rendered as a plain text input with the property
 * key as the label. Long (>100 char) string values get a textarea.
 *
 * Why not RJSF: its default theme is Bootstrap, so without pulling in
 * Bootstrap CSS the additional-properties UI renders as a label+input
 * pair with no spacing, collapsing the key and value into a single
 * run-on string (e.g. "Emailsarah@halcyonlabs.com", "roleCEO"). That's
 * the bug the user is hitting. Our schemas are simple enough that
 * hand-rolling is cheaper than custom RJSF templates.
 */

type SchemaField = {
  type?: string | string[];
  title?: string;
  description?: string;
  format?: string;
  enum?: Array<string | number>;
  default?: unknown;
};

type Schema = {
  type?: string;
  properties?: Record<string, SchemaField>;
  additionalProperties?: boolean | SchemaField;
  required?: string[];
};

interface PropsEditorProps {
  schema: Schema | null | undefined;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  disabled?: boolean;
}

export function PropsEditor({
  schema,
  value,
  onChange,
  disabled = false,
}: PropsEditorProps) {
  const declared = React.useMemo(() => schema?.properties ?? {}, [schema]);
  const allowsAdditional = schema?.additionalProperties !== false;

  // Keys in `value` that aren't declared — "extra" properties. We keep
  // this list stable across renders so adding/removing doesn't reorder
  // the user's rows from under their cursor.
  const [extraKeys, setExtraKeys] = React.useState<string[]>(() => {
    return Object.keys(value).filter((k) => !(k in declared));
  });
  React.useEffect(() => {
    // Reconcile: keep the existing order, append new extras, drop vanished.
    const inValue = new Set(Object.keys(value).filter((k) => !(k in declared)));
    setExtraKeys((prev) => {
      const kept = prev.filter((k) => inValue.has(k));
      for (const k of inValue) {
        if (!kept.includes(k)) kept.push(k);
      }
      return kept;
    });
  }, [value, declared]);

  function setField(key: string, next: unknown): void {
    onChange({ ...value, [key]: next });
  }
  function removeField(key: string): void {
    const { [key]: _removed, ...rest } = value;
    onChange(rest);
  }
  function renameKey(oldKey: string, newKey: string): void {
    if (oldKey === newKey) return;
    const { [oldKey]: moved, ...rest } = value;
    if (newKey in rest && newKey in declared) return;
    onChange({ ...rest, [newKey]: moved });
    setExtraKeys((prev) => prev.map((k) => (k === oldKey ? newKey : k)));
  }
  function addExtra(): void {
    // Find a unique "property", "property_2", ... placeholder.
    const base = "property";
    let n = 1;
    let candidate = base;
    const taken = new Set([...Object.keys(value), ...Object.keys(declared)]);
    while (taken.has(candidate)) {
      n += 1;
      candidate = `${base}_${n}`;
    }
    setExtraKeys((prev) => [...prev, candidate]);
    onChange({ ...value, [candidate]: "" });
  }

  if (
    Object.keys(declared).length === 0 &&
    extraKeys.length === 0 &&
    !allowsAdditional
  ) {
    return (
      <div className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
        No fields for this type.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {Object.entries(declared).map(([key, field]) => (
        <DeclaredField
          key={key}
          keyName={key}
          field={field}
          value={value[key]}
          disabled={disabled}
          onChange={(v) => setField(key, v)}
        />
      ))}

      {allowsAdditional && (
        <div className="space-y-2">
          {(Object.keys(declared).length > 0 || extraKeys.length > 0) && (
            <div className="flex items-center justify-between pb-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Additional properties
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={addExtra}
                disabled={disabled}
              >
                <PiPlus className="h-3.5 w-3.5" /> Add
              </Button>
            </div>
          )}
          {extraKeys.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No extra properties. Click{" "}
              <span className="font-medium">Add</span> to record one.
            </p>
          ) : (
            <ul className="space-y-2">
              {extraKeys.map((k) => (
                <li
                  key={k}
                  className="grid grid-cols-[minmax(120px,1fr)_minmax(160px,2fr)_auto] items-center gap-2"
                >
                  <Input
                    value={k}
                    disabled={disabled}
                    onChange={(e) => renameKey(k, e.target.value)}
                    placeholder="key"
                    className="h-8 text-xs"
                  />
                  <Input
                    value={stringifyValue(value[k])}
                    disabled={disabled}
                    onChange={(e) =>
                      setField(k, parseInputValue(e.target.value))
                    }
                    placeholder="value"
                    className="h-8 text-xs"
                  />
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      removeField(k);
                      setExtraKeys((prev) => prev.filter((x) => x !== k));
                    }}
                    disabled={disabled}
                    aria-label={`Remove ${k}`}
                    className="h-8 w-8"
                  >
                    <PiTrash className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

interface DeclaredFieldProps {
  keyName: string;
  field: SchemaField;
  value: unknown;
  disabled: boolean;
  onChange: (next: unknown) => void;
}

function DeclaredField({
  keyName,
  field,
  value,
  disabled,
  onChange,
}: DeclaredFieldProps) {
  const label = field.title ?? prettyKey(keyName);
  const type = Array.isArray(field.type) ? field.type[0] : field.type;
  const description = field.description;
  const common = { id: `prop-${keyName}`, disabled };

  // Select (enum)
  if (Array.isArray(field.enum) && field.enum.length > 0) {
    return (
      <FieldShell htmlFor={common.id} label={label} description={description}>
        <Select
          {...common}
          value={stringifyValue(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">—</option>
          {field.enum.map((v) => (
            <option key={String(v)} value={String(v)}>
              {String(v)}
            </option>
          ))}
        </Select>
      </FieldShell>
    );
  }

  // Booleans → checkbox
  if (type === "boolean") {
    return (
      <label
        htmlFor={common.id}
        className="flex cursor-pointer items-center gap-2 text-sm"
      >
        <input
          {...common}
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 cursor-pointer"
        />
        <span className="font-medium">{label}</span>
        {description && (
          <span className="text-xs text-muted-foreground">— {description}</span>
        )}
      </label>
    );
  }

  // Numbers
  if (type === "number" || type === "integer") {
    return (
      <FieldShell htmlFor={common.id} label={label} description={description}>
        <Input
          {...common}
          type="number"
          step={type === "integer" ? 1 : undefined}
          value={
            typeof value === "number" || typeof value === "string"
              ? String(value)
              : ""
          }
          onChange={(e) => {
            const n = e.target.value === "" ? null : Number(e.target.value);
            onChange(n);
          }}
        />
      </FieldShell>
    );
  }

  // String with format
  if (type === "string" || type === undefined) {
    const str = stringifyValue(value);
    if (field.format === "date") {
      return (
        <FieldShell htmlFor={common.id} label={label} description={description}>
          <Input
            {...common}
            type="date"
            value={str}
            onChange={(e) => onChange(e.target.value || null)}
          />
        </FieldShell>
      );
    }
    if (field.format === "date-time") {
      return (
        <FieldShell htmlFor={common.id} label={label} description={description}>
          <Input
            {...common}
            type="datetime-local"
            value={str.slice(0, 16)}
            onChange={(e) => onChange(e.target.value || null)}
          />
        </FieldShell>
      );
    }
    if (field.format === "email") {
      return (
        <FieldShell htmlFor={common.id} label={label} description={description}>
          <Input
            {...common}
            type="email"
            value={str}
            onChange={(e) => onChange(e.target.value)}
          />
        </FieldShell>
      );
    }
    if (field.format === "uri" || field.format === "url") {
      return (
        <FieldShell htmlFor={common.id} label={label} description={description}>
          <Input
            {...common}
            type="url"
            value={str}
            onChange={(e) => onChange(e.target.value)}
          />
        </FieldShell>
      );
    }
    // Long string → textarea
    if (str.length > 100 || keyName.toLowerCase() === "bio") {
      return (
        <FieldShell htmlFor={common.id} label={label} description={description}>
          <Textarea
            {...common}
            value={str}
            rows={3}
            onChange={(e) => onChange(e.target.value)}
          />
        </FieldShell>
      );
    }
    return (
      <FieldShell htmlFor={common.id} label={label} description={description}>
        <Input
          {...common}
          type="text"
          value={str}
          onChange={(e) => onChange(e.target.value)}
        />
      </FieldShell>
    );
  }

  // Unknown / object / array — stringified JSON textarea fallback.
  return (
    <FieldShell htmlFor={common.id} label={label} description={description}>
      <Textarea
        {...common}
        value={
          typeof value === "string"
            ? value
            : JSON.stringify(value ?? "", null, 2)
        }
        rows={3}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="mt-1 text-xs text-muted-foreground">
        Complex type — stored as-is.
      </p>
    </FieldShell>
  );
}

function FieldShell({
  htmlFor,
  label,
  description,
  children,
}: {
  htmlFor: string;
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  );
}

function prettyKey(key: string): string {
  const spaced = key.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function stringifyValue(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function parseInputValue(raw: string): unknown {
  // Numeric-looking strings stay strings — the user can type "10" as a
  // quantity and mean the text "10". Only coerce `true`/`false`, which
  // are unambiguous booleans.
  if (raw === "true") return true;
  if (raw === "false") return false;
  return raw;
}
