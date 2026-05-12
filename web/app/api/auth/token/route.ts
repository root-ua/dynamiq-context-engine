import { type NextRequest, NextResponse } from "next/server";
import jwt from "jsonwebtoken";
import { Pool } from "pg";

import { auth } from "@/lib/auth";

/**
 * Mint a short-lived HS256 JWT from the current BetterAuth session.
 *
 * FastAPI and Hocuspocus verify this token with the shared JWT_SECRET.
 * Clients call this endpoint from the API client (and the Hocuspocus
 * provider bootstrap) whenever they need a fresh bearer token.
 *
 * The `?workspace=<uuid>` query is validated against `workspace_member`
 * before it's stamped into the claim. Belt-and-suspenders: the backend
 * also re-verifies membership on every request, but checking here keeps
 * a forged claim from ever reaching the wire.
 */

// Re-use a single pool across requests in the Node runtime. This file
// only runs on the server, so there's no hot-reload concern.
const pool = new Pool({ connectionString: process.env.POSTGRES_URL });

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function isMember(userId: string, workspaceId: string): Promise<boolean> {
  if (!UUID_RE.test(userId) || !UUID_RE.test(workspaceId)) return false;
  const { rows } = await pool.query<{ one: number }>(
    "SELECT 1 AS one FROM workspace_member WHERE user_id = $1 AND workspace_id = $2",
    [userId, workspaceId],
  );
  return rows.length > 0;
}

export async function GET(request: NextRequest) {
  const session = await auth.api.getSession({ headers: request.headers });
  if (!session?.user) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const secret = process.env.JWT_SECRET;
  if (!secret) {
    return NextResponse.json(
      { error: "server missing JWT_SECRET" },
      { status: 500 },
    );
  }

  const issuer = process.env.JWT_ISSUER || "dynamiq-context-engine";
  const algorithm = (process.env.JWT_ALGORITHM as jwt.Algorithm) || "HS256";
  // Match backend `settings.mcp_resource_url` = `${PUBLIC_BASE_URL}/api/mcp`
  // so tokens bind to this resource server per RFC 8707.
  const audience =
    (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
      /\/$/,
      "",
    ) + "/api/mcp";

  const requestedWorkspace = request.nextUrl.searchParams.get("workspace");
  let workspaceClaim: string | undefined;
  if (requestedWorkspace) {
    if (await isMember(session.user.id, requestedWorkspace)) {
      workspaceClaim = requestedWorkspace;
    } else {
      return NextResponse.json(
        { error: "not a member of requested workspace" },
        { status: 403 },
      );
    }
  }

  const token = jwt.sign(
    {
      sub: session.user.id,
      email: session.user.email,
      name: session.user.name,
      workspace_id: workspaceClaim,
    },
    secret,
    {
      algorithm,
      issuer,
      audience,
      expiresIn: 60 * 60,
    },
  );

  return NextResponse.json({ token });
}
