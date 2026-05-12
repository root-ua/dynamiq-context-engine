"""OAuth 2.0 Protected Resource Metadata (RFC 9728) + related discovery.

MCP clients that support the full OAuth 2.1 flow read this document to
discover which authorization servers to use. We don't run a full AS (we
accept static bearer tokens), so the metadata advertises ourselves as the
issuer and leaves fancier flows to future work. Clients that can't dance
the full flow will fall back to the `Authorization: Bearer` header, which
is the intended happy path for Claude Code / Cursor.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata() -> dict[str, object]:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    return {
        "resource": settings.mcp_resource_url,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base}/docs",
        "scopes_supported": ["mcp"],
    }
