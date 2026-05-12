/**
 * Yjs ↔ block-tree projection.
 *
 * Uses BlockNote's ServerBlockNoteEditor to deserialize the Yjs XmlFragment
 * at key "document-store" into a native BlockNote block tree, then flattens
 * it into a denormalized list suitable for the backend's
 * PUT /documents/:id/blocks endpoint.
 */
import * as Y from "yjs";
import { ServerBlockNoteEditor } from "@blocknote/server-util";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";

import { memorySchema } from "./schema.js";

interface ProjectedBlock {
  id: string;
  parent_block_id: string | null;
  position: number;
  block_type: string;
  content: unknown;
  props: Record<string, unknown>;
  search_text: string;
}

const pool = new Pool({ connectionString: process.env.POSTGRES_URL });

/**
 * Reverse projection: BlockNote blocks → Yjs binary state.
 *
 * Used by the demo seeder via the /internal/hydrate-yjs HTTP route.
 * BlockNote's collaborative editor reads and writes to an XmlFragment
 * named "document-store" — we must pass the same name here or the
 * client will see an empty doc despite non-empty yjs_state bytes.
 *
 * Returns the full encoded Y.Doc update suitable for writing directly
 * into document.yjs_state; on first open Hocuspocus passes these bytes
 * straight through to the client's Yjs provider.
 */
export function projectBlocksToYjs(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  blocks: any[],
): Uint8Array {
  const editor = ServerBlockNoteEditor.create({ schema: memorySchema });
  const ydoc = editor.blocksToYDoc(blocks, "document-store");
  return Y.encodeStateAsUpdate(ydoc);
}

export async function projectYjsToBlocks(doc: Y.Doc): Promise<ProjectedBlock[]> {
  const editor = ServerBlockNoteEditor.create();
  const fragment = doc.getXmlFragment("document-store");

  // ServerBlockNoteEditor understands the Yjs fragment shape BlockNote writes.
  const blocks = editor.yXmlFragmentToBlocks(fragment);

  const out: ProjectedBlock[] = [];
  walk(blocks, null, out);
  return out;
}

function walk(
  blocks: Array<Record<string, unknown>>,
  parent: string | null,
  out: ProjectedBlock[],
): void {
  blocks.forEach((b, idx) => {
    const id = (typeof b.id === "string" && b.id.length > 0) ? b.id : randomUUID();
    const type = typeof b.type === "string" ? b.type : "paragraph";
    const content = b.content ?? null;
    const props = (b.props as Record<string, unknown>) ?? {};
    out.push({
      id,
      parent_block_id: parent,
      position: idx,
      block_type: type,
      content,
      props,
      search_text: plainText(content),
    });
    const children = (b.children as Array<Record<string, unknown>>) ?? [];
    if (children.length) walk(children, id, out);
  });
}

function plainText(content: unknown): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map(plainText).filter(Boolean).join(" ");
  }
  if (typeof content === "object") {
    const c = content as Record<string, unknown>;
    const direct = typeof c.text === "string" ? (c.text as string) : "";
    const type = typeof c.type === "string" ? (c.type as string) : "";
    if (type === "entityMention") {
      const props = (c.props as Record<string, unknown>) ?? {};
      const label = typeof props.fallbackLabel === "string" ? (props.fallbackLabel as string) : "";
      return label ? `@${label}` : "";
    }
    if (direct) return direct;
    if (Array.isArray(c.content)) return plainText(c.content);
  }
  return "";
}

export async function persistBlocks(opts: {
  documentId: string;
  workspaceId: string;
  blocks: ProjectedBlock[];
}): Promise<void> {
  const { documentId, workspaceId, blocks } = opts;

  // We write directly against Postgres with the workspace set via SET LOCAL,
  // mirroring the backend's RLS discipline.
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      "SELECT set_config('app.current_workspace_id', $1, true)",
      [workspaceId],
    );

    const ids = blocks.map((b) => b.id);
    await client.query(
      `UPDATE block SET deleted_at = now()
       WHERE document_id = $1 AND deleted_at IS NULL AND NOT (id = ANY($2))`,
      [documentId, ids.length ? ids : ["00000000-0000-0000-0000-000000000000"]],
    );

    for (const b of blocks) {
      await client.query(
        `
        INSERT INTO block
          (id, workspace_id, document_id, parent_block_id, position,
           block_type, content, props, version, search_text, deleted_at)
        VALUES
          ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, 1, $9, NULL)
        ON CONFLICT (id) DO UPDATE SET
          parent_block_id = EXCLUDED.parent_block_id,
          position = EXCLUDED.position,
          block_type = EXCLUDED.block_type,
          content = EXCLUDED.content,
          props = EXCLUDED.props,
          search_text = EXCLUDED.search_text,
          version = block.version + 1,
          deleted_at = NULL
        `,
        [
          b.id,
          workspaceId,
          documentId,
          b.parent_block_id,
          b.position,
          b.block_type,
          JSON.stringify(b.content ?? {}),
          JSON.stringify(b.props ?? {}),
          b.search_text,
        ],
      );
    }

    // Rebuild block_entity_ref from mentions found in the serialized content.
    await client.query(
      `DELETE FROM block_entity_ref
       WHERE block_id IN (SELECT id FROM block WHERE document_id = $1)`,
      [documentId],
    );

    const refs = blocks.flatMap((b) =>
      extractMentionIds(b.content).map((entityId, idx) => ({
        block_id: b.id,
        entity_id: entityId,
        position: idx,
      })),
    );
    for (const r of refs) {
      await client.query(
        `INSERT INTO block_entity_ref
           (id, workspace_id, block_id, entity_id, mention_type, position)
         VALUES (gen_random_uuid(), $1, $2, $3, 'mention', $4)
         ON CONFLICT DO NOTHING`,
        [workspaceId, r.block_id, r.entity_id, r.position],
      );
    }

    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }
}

function extractMentionIds(node: unknown): string[] {
  const out: string[] = [];
  const visit = (n: unknown): void => {
    if (!n) return;
    if (Array.isArray(n)) {
      n.forEach(visit);
      return;
    }
    if (typeof n === "object") {
      const obj = n as Record<string, unknown>;
      if (obj.type === "entityMention") {
        const props = (obj.props as Record<string, unknown>) ?? {};
        const id = props.entityId;
        if (typeof id === "string") out.push(id);
      }
      if (obj.content) visit(obj.content);
      if (obj.children) visit(obj.children);
    }
  };
  visit(node);
  return out;
}
