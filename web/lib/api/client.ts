const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_URL = "/api/auth/token";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `api error ${status}`);
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  workspaceId?: string | null;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

// In-memory token cache. Re-minted automatically when it ages out.
let cache: {
  token: string;
  expiresAt: number;
  workspaceId: string | null;
} | null = null;

/**
 * Fetch (and cache) a short-lived HS256 JWT minted by the Next.js
 * /api/auth/token route from the active BetterAuth session. FastAPI and
 * Hocuspocus verify this with the same JWT_SECRET.
 */
export async function getToken(
  workspaceId: string | null = null,
): Promise<string | null> {
  const now = Date.now();
  if (
    cache?.token &&
    cache.workspaceId === workspaceId &&
    cache.expiresAt - now > 30_000
  ) {
    return cache.token;
  }

  const url = workspaceId
    ? `${TOKEN_URL}?workspace=${encodeURIComponent(workspaceId)}`
    : TOKEN_URL;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) {
    cache = null;
    return null;
  }
  const body = (await res.json()) as { token?: string };
  if (!body.token) {
    cache = null;
    return null;
  }
  // Tokens are minted with `expiresIn: 60 * 60`. Cache for 55 min to leave
  // a cushion against clock skew and network roundtrip.
  cache = {
    token: body.token,
    expiresAt: now + 55 * 60 * 1000,
    workspaceId,
  };
  return body.token;
}

export function invalidateTokenCache(): void {
  cache = null;
}

export async function api<T = unknown>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_URL}${path}`;

  const token = await getToken(opts.workspaceId ?? null);
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...opts.headers,
  };
  if (opts.body != null) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts.workspaceId) headers["X-Workspace-Id"] = opts.workspaceId;

  const res = await fetch(url, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body != null ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
    credentials: "include",
  });

  if (!res.ok) {
    // Token may have expired under us; bust the cache so the next call
    // re-mints. Don't auto-retry here — let the caller decide.
    if (res.status === 401) invalidateTokenCache();
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(
      res.status,
      body,
      extractMessage(body) ?? `api error ${res.status}`,
    );
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function extractMessage(body: unknown): string | null {
  if (body && typeof body === "object" && "detail" in body) {
    const d = body.detail;
    if (typeof d === "string") return d;
  }
  return null;
}
