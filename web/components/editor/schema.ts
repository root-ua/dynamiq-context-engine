"use client";
import {
  BlockNoteSchema,
  defaultBlockSpecs,
  defaultInlineContentSpecs,
  defaultStyleSpecs,
  type BlockNoteEditor,
} from "@blocknote/core";

import { EntityMention } from "@/components/editor/EntityMention";

/**
 * Extended BlockNote schema that registers the `entityMention` inline
 * content spec. Everything else is the default set.
 */
export const memorySchema = BlockNoteSchema.create({
  blockSpecs: defaultBlockSpecs,
  inlineContentSpecs: {
    ...defaultInlineContentSpecs,
    entityMention: EntityMention,
  },
  styleSpecs: defaultStyleSpecs,
});

export type MemoryEditor = BlockNoteEditor<
  typeof memorySchema.blockSchema,
  typeof memorySchema.inlineContentSchema,
  typeof memorySchema.styleSchema
>;

export interface EntityMentionProps {
  entityId: string;
  entityType: string;
  fallbackLabel: string;
}

/**
 * Insert an entity mention at the current selection, trimming the trailing
 * slash-menu trigger if present and appending a trailing space so typing
 * can continue naturally.
 */
export function insertEntityMention(
  editor: MemoryEditor,
  props: EntityMentionProps,
): void {
  editor.insertInlineContent([
    {
      type: "entityMention",
      props,
    },
    " ",
  ]);
}

/** Plain-text of the currently focused block (no children). */
export function getCurrentBlockText(editor: MemoryEditor): string {
  const cursor = editor.getTextCursorPosition();
  if (!cursor?.block) return "";
  const parts: string[] = [];
  const content = (cursor.block as { content?: unknown }).content;
  if (Array.isArray(content)) {
    for (const node of content) {
      if (!node || typeof node !== "object") continue;
      const n = node as { type?: string; text?: string };
      if (n.type === "text" && typeof n.text === "string") parts.push(n.text);
    }
  }
  return parts.join("").trim();
}

/**
 * Crude n-gram extractor: takes the last `count` whitespace-split tokens
 * and returns them as candidate phrases (1-word, 2-word, 3-word) so the
 * user can pick which one to search for. Not a real NLP model but good
 * enough to drive the "Ask AI to link entities" UI.
 */
export function lastNGrams(text: string, count = 3): string[] {
  const tokens = text
    .replace(/[^\p{L}\p{N}\s'-]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (tokens.length === 0) return [];
  const out = new Set<string>();
  const maxN = Math.min(count, tokens.length);
  for (let n = 1; n <= maxN; n++) {
    const slice = tokens.slice(tokens.length - n);
    out.add(slice.join(" "));
  }
  return Array.from(out);
}
