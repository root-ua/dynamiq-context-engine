"""Agent-token REST endpoints — mint, list, revoke.

Tokens are scoped to the active workspace (selected via JWT `workspace_id`
or the `X-Workspace-Id` header). The plaintext token is returned **once**
at creation time; list never returns it.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, DbSession
from app.domain import agent_token as tokens

router = APIRouter(prefix="/agent-tokens", tags=["agent-tokens"])


class TokenCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    kind: str = Field(default="service", pattern="^(user|service)$")
    scopes: list[str] | None = Field(default=None)


class TokenOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: str | None
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    kind: str = "service"


class TokenCreateOut(TokenOut):
    token: str


@router.get("")
async def list_tokens(
    principal: CurrentPrincipal, session: DbSession
) -> list[TokenOut]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    rows = await tokens.list_tokens(session, workspace_id=principal.workspace_id)
    return [TokenOut(**asdict(r)) for r in rows]


@router.post("", status_code=201)
async def create_agent_token(
    payload: TokenCreateIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> TokenCreateOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    if principal.claims.get("kind") == "agent_token":
        # Agent tokens can't mint new agent tokens — prevents privilege
        # escalation if a token is leaked.
        raise HTTPException(403, "agent tokens cannot mint new tokens")
    expires_at = (
        datetime.now(tz=UTC) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days is not None
        else None
    )
    # Personal user-kind tokens authenticate as the requesting user. Only
    # the user themselves should mint one — and only via a session JWT
    # (we already block agent-token-mints-token above).
    if payload.kind == "user" and principal.kind != "user":
        raise HTTPException(403, "user-kind tokens can only be minted by user principals")
    created = await tokens.create_token(
        session,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        name=payload.name,
        kind=payload.kind,
        scopes=payload.scopes,
        expires_at=expires_at,
    )
    return TokenCreateOut(**asdict(created.row), token=created.token)


@router.delete("/{token_id}", status_code=204)
async def revoke_agent_token(
    token_id: str, principal: CurrentPrincipal, session: DbSession
) -> None:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    ok = await tokens.revoke_token(
        session, workspace_id=principal.workspace_id, token_id=token_id
    )
    if not ok:
        raise HTTPException(404, "token not found or already revoked")


@router.post("/{token_id}/rotate", status_code=200)
async def rotate_agent_token(
    token_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> TokenCreateOut:
    """Revoke the existing token and mint a new one with the same name,
    user, scopes, kind, and expiry. The plaintext is shown once."""
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot rotate themselves")
    created = await tokens.rotate_token(
        session,
        workspace_id=principal.workspace_id,
        token_id=token_id,
    )
    if not created:
        raise HTTPException(404, "token not found or already revoked")
    return TokenCreateOut(**asdict(created.row), token=created.token)
