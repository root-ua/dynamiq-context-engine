/**
 * Hocuspocus server for Yjs collaborative editing of BlockNote documents.
 *
 * Document name convention: `doc:<document_id>` where `document_id` is the
 * UUID primary key of the `document` row. On every persisted change we:
 *   1. Store the raw Yjs binary state in `document.yjs_state` (collaboration
 *      wire format).
 *   2. Project the Yjs doc through BlockNote's ServerBlockNoteEditor to a
 *      queryable block tree and upsert it via the backend's
 *      `PUT /api/documents/:id/blocks` endpoint.
 *
 * Authentication is a bearer JWT shared with the FastAPI backend. We verify
 * workspace membership on connect and reject unauthorized sessions.
 */
import type { IncomingMessage, ServerResponse } from "node:http";
import { Server } from "@hocuspocus/server";
import { Database } from "@hocuspocus/extension-database";
import { Logger } from "@hocuspocus/extension-logger";
import { Pool } from "pg";

import { verifyToken } from "./auth.js";
import {
  persistBlocks,
  projectBlocksToYjs,
  projectYjsToBlocks,
} from "./projection.js";

const PORT = Number(process.env.COLLAB_PORT ?? 1234);
const POSTGRES_URL = process.env.POSTGRES_URL!;
const HYDRATE_SECRET = process.env.HYDRATE_SECRET;
const pool = new Pool({ connectionString: POSTGRES_URL });

const server = Server.configure({
  port: PORT,
  extensions: [
    new Logger(),
    new Database({
      fetch: async ({ documentName }) => {
        const docId = parseDocId(documentName);
        if (!docId) return null;
        const { rows } = await pool.query<{ yjs_state: Buffer | null }>(
          "SELECT yjs_state FROM document WHERE id = $1",
          [docId],
        );
        return rows[0]?.yjs_state ?? null;
      },
      store: async ({ documentName, state, document }) => {
        const docId = parseDocId(documentName);
        if (!docId) return;

        await pool.query(
          "UPDATE document SET yjs_state = $2, updated_at = now() WHERE id = $1",
          [docId, state],
        );

        // Best-effort projection to the block tree. Errors are logged but
        // don't fail the persistence path; the Yjs blob remains authoritative.
        try {
          const blocks = await projectYjsToBlocks(document);
          const workspaceId = await getWorkspaceIdForDocument(docId);
          if (workspaceId) {
            await persistBlocks({ documentId: docId, workspaceId, blocks });
          }
        } catch (err) {
          console.error("collab.projection.failed", docId, err);
        }
      },
    }),
  ],

  // Internal HTTP route: the demo seeder POSTs a block tree here and
  // gets back a Yjs binary update it writes into document.yjs_state.
  //
  // Returning a resolved promise with the response already ended signals
  // to Hocuspocus that we handled the request; throwing an empty
  // rejection short-circuits the default `200 OK` handler it would send
  // otherwise.
  async onRequest({ request, response }): Promise<void> {
    if (request.method === "POST" && request.url === "/internal/hydrate-yjs") {
      await handleHydrate(request, response);
      // Empty rejection tells Hocuspocus "we wrote the response ourselves".
      throw null;
    }
  },

  async onAuthenticate({ token, documentName }) {
    const principal = await verifyToken(token);
    if (!principal) throw new Error("unauthorized: invalid token");
    const docId = parseDocId(documentName);
    if (!docId) throw new Error("bad document name");

    // Verify workspace membership for this specific document.
    const { rows } = await pool.query<{ workspace_id: string }>(
      "SELECT workspace_id::text FROM document WHERE id = $1",
      [docId],
    );
    const docWs = rows[0]?.workspace_id;
    if (!docWs) throw new Error("document not found");

    const membership = await pool.query<{ role: string }>(
      `SELECT role FROM workspace_member
       WHERE workspace_id = $1 AND user_id = $2`,
      [docWs, principal.userId],
    );
    if (membership.rows.length === 0) {
      throw new Error("unauthorized: not a workspace member");
    }

    return { user: principal, documentName, workspaceId: docWs };
  },
});

async function handleHydrate(
  request: IncomingMessage,
  response: ServerResponse,
): Promise<void> {
  if (!HYDRATE_SECRET) {
    response.writeHead(503, { "Content-Type": "text/plain" });
    response.end("HYDRATE_SECRET not configured");
    return;
  }
  const provided = request.headers["x-internal-auth"];
  if (provided !== HYDRATE_SECRET) {
    response.writeHead(401, { "Content-Type": "text/plain" });
    response.end("bad or missing X-Internal-Auth");
    return;
  }
  try {
    const body = await readJsonBody(request);
    const blocks = (body as { blocks?: unknown }).blocks;
    if (!Array.isArray(blocks)) {
      response.writeHead(400, { "Content-Type": "text/plain" });
      response.end('body must be {"blocks":[...]}');
      return;
    }
    const bytes = projectBlocksToYjs(blocks as Array<Record<string, unknown>>);
    response.writeHead(200, {
      "Content-Type": "application/octet-stream",
      "Content-Length": String(bytes.byteLength),
    });
    response.end(Buffer.from(bytes));
  } catch (err) {
    console.error("collab.hydrate.failed", err);
    response.writeHead(500, { "Content-Type": "text/plain" });
    response.end(`hydrate failed: ${(err as Error).message}`);
  }
}

async function readJsonBody(
  request: IncomingMessage,
  maxBytes = 4 * 1024 * 1024,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let total = 0;
    const chunks: Buffer[] = [];
    request.on("data", (c: Buffer) => {
      total += c.length;
      if (total > maxBytes) {
        reject(new Error("request body too large"));
        request.destroy();
        return;
      }
      chunks.push(c);
    });
    request.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (err) {
        reject(err);
      }
    });
    request.on("error", reject);
  });
}

function parseDocId(name: string): string | null {
  const m = name.match(/^doc:([0-9a-f-]{36})$/i);
  return m && m[1] ? m[1] : null;
}

async function getWorkspaceIdForDocument(docId: string): Promise<string | null> {
  const { rows } = await pool.query<{ workspace_id: string }>(
    "SELECT workspace_id::text FROM document WHERE id = $1",
    [docId],
  );
  return rows[0]?.workspace_id ?? null;
}

server
  .listen()
  .then(() => console.log(`hocuspocus listening on :${PORT}`))
  .catch((err) => {
    console.error("hocuspocus failed to start", err);
    process.exit(1);
  });
