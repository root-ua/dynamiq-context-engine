import { NextResponse } from "next/server";

/**
 * Simple liveness probe. Returns 200 if the Next.js runtime is up.
 *
 * Render's auto-healthcheck path is configurable via `render.yaml`; this
 * endpoint is also wired into the Dockerfile HEALTHCHECK so compose and
 * any other orchestrator can tell us apart from a wedged container.
 */
export function GET() {
  return NextResponse.json({ status: "ok" });
}
