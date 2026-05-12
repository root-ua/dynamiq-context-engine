import type { Entity } from "@/lib/api/types";

export type GraphDirection = "out" | "in" | "both";

export type ThemeMode = "light" | "dark";

export interface GraphFiltersValue {
  types: string[];
  predicates: string[];
  direction: GraphDirection;
  maxHops: number;
  asOf: string | null;
}

export const DEFAULT_FILTERS: GraphFiltersValue = {
  types: [],
  predicates: [],
  direction: "both",
  maxHops: 2,
  asOf: null,
};

export interface SeedEntity {
  id: string;
  canonical: string;
  type: string | null;
}

export function toSeedEntity(e: Entity): SeedEntity {
  return { id: e.id, canonical: e.canonical, type: e.type_slug };
}

/**
 * Stable hash → HSL color. Deterministic per-string so every occurrence
 * of a type slug gets the same hue on every render. The optional `mode`
 * shifts lightness so fills stay legible against both backgrounds — hue
 * is the same either way, which keeps the type ↔ color association
 * consistent when the user toggles themes.
 */
export function colorForType(type: string, mode: ThemeMode = "light"): string {
  let hash = 0;
  for (let i = 0; i < type.length; i += 1) {
    hash = (hash * 31 + type.charCodeAt(i)) | 0;
  }
  const hue = Math.abs(hash) % 360;
  const lightness = mode === "dark" ? 68 : 52;
  const saturation = mode === "dark" ? 58 : 62;
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}
