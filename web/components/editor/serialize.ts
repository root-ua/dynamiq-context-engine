"use client";
import type { Block } from "@blocknote/core";

export interface ProjectedBlock {
  id: string;
  parent_block_id: string | null;
  position: number;
  block_type: string;
  content: unknown;
  props: Record<string, unknown>;
  search_text: string;
}

/**
 * Extract a plain-text representation of a single block, ignoring its
 * nested children (those are serialized separately).
 */
function extractBlockText(block: Block): string {
  const parts: string[] = [];
  const content = (block as { content?: unknown }).content;
  if (Array.isArray(content)) {
    for (const node of content) {
      if (!node || typeof node !== "object") continue;
      const n = node as {
        type?: string;
        text?: string;
        props?: Record<string, unknown>;
      };
      if (n.type === "text" && typeof n.text === "string") {
        parts.push(n.text);
        continue;
      }
      if (
        n.type === "link" &&
        Array.isArray((n as { content?: unknown }).content)
      ) {
        for (const inner of (n as { content: unknown[] }).content) {
          if (inner && typeof inner === "object") {
            const i = inner as { text?: string };
            if (typeof i.text === "string") parts.push(i.text);
          }
        }
        continue;
      }
      if (n.type === "entityMention") {
        const props = n.props ?? {};
        const label =
          (props.fallbackLabel as string | undefined) ??
          (props.entityId as string | undefined) ??
          "";
        if (label) parts.push(`@${label}`);
        continue;
      }
    }
  } else if (typeof content === "string") {
    parts.push(content);
  }
  return parts.join("").trim();
}

/**
 * Project BlockNote's editor.document tree into the flat shape expected
 * by the backend `replaceBlocks` endpoint. Children are walked recursively
 * and `position` is the sibling index as a float so clients can insert
 * between blocks later without reindexing everything.
 */
export function projectBlocks(blocks: Block[]): ProjectedBlock[] {
  const out: ProjectedBlock[] = [];

  const walk = (nodes: Block[], parentId: string | null) => {
    nodes.forEach((block, index) => {
      const children = (block.children ?? []) as Block[];
      const search_text = extractBlockText(block);
      const content = (block as { content?: unknown }).content ?? null;
      out.push({
        id: block.id,
        parent_block_id: parentId,
        position: Number(index),
        block_type: block.type,
        content,
        props: block.props ?? {},
        search_text,
      });
      if (children.length > 0) walk(children, block.id);
    });
  };

  walk(blocks, null);
  return out;
}

// Accepts any editor-like object with a `document` array. We use a structural
// type here because BlockNote's generic `BlockNoteEditor` type identity can
// differ across transitive module instances (pnpm + Next.js transpile), and
// this serializer only touches the document tree — no editor methods.
export function projectEditor(editor: { document: unknown }): ProjectedBlock[] {
  return projectBlocks(editor.document as Block[]);
}
