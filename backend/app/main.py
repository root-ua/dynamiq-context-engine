from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.mcp.server import router as mcp_router
from app.api.rest import router as rest_router
from app.api.websocket.events import router as ws_router
from app.api.well_known import router as well_known_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative security headers to every response.

    These are framework-agnostic defaults; the web app layers its own
    headers on top (see web/next.config.js). We set them here too so
    direct API consumers (MCP clients, curl, browser-side requests that
    skip Next.js) get the same baseline.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        # The backend returns JSON / small JSON-RPC payloads only — no
        # inline scripts, no iframes — so a tight CSP is safe.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        )
        return response


def _init_sentry() -> None:
    """Best-effort Sentry init. Silently skips if DSN is unset or the SDK
    isn't installed (e.g. slim CI images).
    """
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        log.warning("sentry.sdk.missing")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            AsyncioIntegration(),
        ],
    )
    log.info("sentry.initialized", env=settings.sentry_environment)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    _init_sentry()
    log.info("backend.startup", env={"llm_model": settings.llm_model})
    yield
    log.info("backend.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Dynamiq Context Engine API",
        description=(
            "Dynamiq Context Engine — a typed, bi-temporal memory layer for "
            "humans and AI agents. Exposes a REST API for the web client "
            "and an MCP server for external agents (Claude Code, Cursor, "
            "Claude Desktop)."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        # Explicit method list — avoids `*` which is incompatible with
        # credentialed requests per CORS spec.
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Workspace-Id",
            "X-Idempotency-Key",
        ],
        expose_headers=["WWW-Authenticate"],
        max_age=600,
    )

    app.include_router(rest_router, prefix="/api")
    app.include_router(mcp_router, prefix="/api")
    app.include_router(ws_router, prefix="/api")
    # /.well-known/* lives at the root so OAuth-discovery clients can find
    # it without an /api prefix; spec-compliant location.
    app.include_router(well_known_router)

    return app


app = create_app()
