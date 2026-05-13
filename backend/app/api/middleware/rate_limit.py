"""Per-token rate limit on the MCP path.

Token-bucket keyed on the agent token's ``Authorization: Bearer mem_…``
prefix. Session JWTs aren't rate-limited here — they're already covered
by BetterAuth's session checks.

Bucket size = ``MCP_RATE_LIMIT_RPM`` (default 60). Refill = same per
minute. State lives in-process: this is a single-node deploy primitive;
move to Redis when running multiple backend replicas.

The middleware is mounted at app-level but only acts on paths that
start with ``/api/mcp/``. Skips entirely otherwise so no overhead on
the REST / WS / health paths.
"""
from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

_BUCKETS: dict[str, list[float]] = defaultdict(list)
_LOCK = Lock()


def _extract_token_prefix(auth_header: str | None) -> str | None:
    """Return the first 8 chars of the random body of a ``mem_…`` token,
    or None for a JWT / missing header."""
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    if not token.startswith("mem_"):
        return None
    body = token[4:]
    return body[:8] if len(body) >= 8 else None


class MCPRateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory token-bucket on ``/api/mcp/*`` for agent tokens.

    The bucket holds wall-clock timestamps of the most recent requests
    that fit in a 60-second window. On each call we drop expired
    entries, count, and either append (under cap) or 429.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith("/api/mcp"):
            return await call_next(request)

        prefix = _extract_token_prefix(request.headers.get("Authorization"))
        if prefix is None:
            return await call_next(request)

        rpm = get_settings().mcp_rate_limit_rpm
        if rpm <= 0:
            return await call_next(request)

        now = time.monotonic()
        wall_now = time.time()
        cutoff = now - 60.0
        with _LOCK:
            window = _BUCKETS[prefix]
            window[:] = [t for t in window if t >= cutoff]
            if len(window) >= rpm:
                retry_after = max(1, int(60 - (now - window[0])))
                reset_epoch = int(wall_now + retry_after)
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "detail": (
                            f"agent token exceeded {rpm} req/min on /api/mcp/*"
                        ),
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(rpm),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_epoch),
                    },
                )
            window.append(now)
            remaining = rpm - len(window)
            # Reset is the time the oldest call in the window expires.
            oldest = window[0]
            reset_epoch = int(wall_now + max(0, int(60 - (now - oldest))))

        response = await call_next(request)
        # Inform well-behaved MCP clients (Claude Code, Cursor) how much
        # quota they have left so they can self-throttle.
        response.headers["X-RateLimit-Limit"] = str(rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_epoch)
        return response
