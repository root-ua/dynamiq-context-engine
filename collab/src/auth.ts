import jwt from "jsonwebtoken";

export interface CollabPrincipal {
  userId: string;
  workspaceId?: string;
  email?: string;
}

export async function verifyToken(
  token: string | undefined,
): Promise<CollabPrincipal | null> {
  if (!token) return null;
  try {
    const secret = process.env.JWT_SECRET!;
    const algorithm = (process.env.JWT_ALGORITHM ?? "HS256") as jwt.Algorithm;
    const issuer = process.env.JWT_ISSUER;
    const publicBase = (
      process.env.PUBLIC_BASE_URL ?? "http://localhost:8000"
    ).replace(/\/$/, "");
    const audience = `${publicBase}/api/mcp`;
    const payload = jwt.verify(token, secret, {
      algorithms: [algorithm],
      issuer,
      audience,
    }) as Record<string, unknown>;
    const sub = payload.sub;
    if (typeof sub !== "string") return null;
    return {
      userId: sub,
      workspaceId:
        typeof payload.workspace_id === "string" ? payload.workspace_id : undefined,
      email: typeof payload.email === "string" ? payload.email : undefined,
    };
  } catch {
    return null;
  }
}
