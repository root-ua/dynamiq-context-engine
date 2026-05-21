from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import AuthError, Principal, decode_token
from app.core.config import get_settings
from app.db.session import session_scope
from app.domain.agent_token import TOKEN_PREFIX, verify_token

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _www_authenticate() -> dict[str, str]:
    """Per RFC 9728 §5.1 / MCP auth spec: advertise resource metadata URL."""
    base = get_settings().public_base_url.rstrip("/")
    return {
        "WWW-Authenticate": (
            f'Bearer realm="dynamiq-context-engine", '
            f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
        )
    }


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=_www_authenticate(),
    )


async def _user_is_member(user_id: str, workspace_id: str) -> bool:
    """Verify (user_id, workspace_id) ∈ workspace_member.

    The web token-mint route stamps `workspace_id` into the JWT from a URL
    query param without checking membership — so a JWT claim is as untrusted
    as the X-Workspace-Id header. Both get funnelled through here before
    we set the RLS tenancy variable.
    """
    if not _UUID_RE.match(workspace_id) or not _UUID_RE.match(user_id):
        return False
    async with session_scope() as session:
        r = await session.execute(
            text(
                "SELECT 1 FROM workspace_member "
                "WHERE user_id = CAST(:u AS uuid) "
                "AND workspace_id = CAST(:w AS uuid)"
            ),
            {"u": user_id, "w": workspace_id},
        )
        return r.first() is not None


def _is_mcp_path(path: str) -> bool:
    return path.startswith("/api/mcp") or path.startswith("/.well-known")


async def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    # Long-lived agent token — one workspace per token, pinned at creation.
    # X-Workspace-Id is ignored for these because the token already carries
    # the binding. Scope controls which paths the token may hit.
    if token.startswith(TOKEN_PREFIX):
        resolved = await verify_token(token)
        if not resolved:
            raise _unauthorized("invalid or revoked agent token")

        # Scope enforcement: default scope `mcp` restricts a token to the
        # MCP surface (+ discovery). Broader scope `rest` opens the full
        # REST API. Anything else is conservative-deny.
        if not _is_mcp_path(request.url.path) and "rest" not in resolved.scopes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="agent token scope does not permit this endpoint",
            )

        # User-kind tokens authenticate as a real user — look up workspace
        # role so admin/owner bypass the per-source ACL filter the same
        # way they do over a session JWT. Service-kind tokens have no
        # role; they bypass via Principal.kind == 'service' in the ACL
        # filter regardless.
        role = (
            await _member_role(resolved.user_id, resolved.workspace_id)
            if resolved.kind == "user"
            else None
        )

        return Principal(
            user_id=resolved.user_id,
            email=None,
            workspace_id=resolved.workspace_id,
            role=role,
            claims={
                "token_id": resolved.token_id,
                "kind": "agent_token",
                "scopes": resolved.scopes,
                "token_kind": resolved.kind,
            },
            kind=resolved.kind,  # type: ignore[arg-type]
        )

    # Session JWT from the Next.js /api/auth/token route.
    try:
        principal = decode_token(token)
    except AuthError as exc:
        raise _unauthorized(f"invalid token: {exc}") from exc

    # Both the JWT `workspace_id` claim and X-Workspace-Id header are
    # user-controlled (the mint route takes the workspace from a query
    # string and does not verify membership). Any workspace selection
    # must be authorized here against workspace_member.
    requested_ws = principal.workspace_id or x_workspace_id
    resolved_ws: str | None = None
    if requested_ws:
        if not await _user_is_member(principal.user_id, requested_ws):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="not a member of requested workspace",
            )
        resolved_ws = requested_ws

    # Session JWTs always represent a real user — kind defaults to "user"
    # in the Principal dataclass, but be explicit.
    #
    # Role: the JWT mint route does not embed a role claim; resolve it
    # from workspace_member here so the per-source ACL filter knows when
    # to bypass for owners/admins. Falls back to whatever the JWT claim
    # said if no membership row exists (legacy callers, internal tools).
    resolved_role = principal.role
    if resolved_ws:
        looked_up = await _member_role(principal.user_id, resolved_ws)
        if looked_up is not None:
            resolved_role = looked_up

    return Principal(
        user_id=principal.user_id,
        email=principal.email,
        workspace_id=resolved_ws,
        role=resolved_role,
        claims=principal.claims,
        kind="user",
    )


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def db_session(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    # Service principals (agent tokens marked `service`, internal callers)
    # bypass the source ACL filter and rely on workspace RLS only.
    # User principals get their email threaded into the session GUCs so the
    # Postgres-side RLS policies enforce per-fact visibility — see
    # migration 20260521_0001 (external_acl_rls).
    bypass = principal.kind == "service"
    async with session_scope(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        user_email=None if bypass else principal.email,
        bypass_external_acl=bypass,
    ) as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(db_session)]


async def _member_role(user_id: str, workspace_id: str) -> str | None:
    async with session_scope() as session:
        r = await session.execute(
            text(
                "SELECT role FROM workspace_member "
                "WHERE user_id = CAST(:u AS uuid) "
                "AND workspace_id = CAST(:w AS uuid)"
            ),
            {"u": user_id, "w": workspace_id},
        )
        row = r.first()
        return row[0] if row else None


def require_workspace_role(*allowed: str):
    """FastAPI dep factory: fail 403 unless the principal holds one of
    the given workspace roles.

    Usage::

        @router.post("/members", dependencies=[Depends(require_workspace_role("owner","admin"))])
    """

    async def _dep(principal: CurrentPrincipal) -> Principal:
        if principal.claims.get("kind") == "agent_token":
            raise HTTPException(
                status_code=403,
                detail="agent tokens cannot manage membership",
            )
        if not principal.workspace_id:
            raise HTTPException(status_code=400, detail="workspace required")
        role = await _member_role(principal.user_id, principal.workspace_id)
        if role is None or role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"requires one of roles: {', '.join(allowed)}",
            )
        return principal

    return _dep
