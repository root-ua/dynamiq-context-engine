"""Workspace member + invite endpoints.

The UI's settings/members page drives this. Owner/admin can mint
invites, revoke them, change roles, and remove members. Everyone in the
workspace can GET the member list (which is a common expectation — you
want to see who else is in your workspace).

Invite acceptance lives at `/api/invites/{token}/accept` (separate
prefix) because the user accepting isn't yet scoped to the workspace.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import CurrentPrincipal, require_workspace_role
from app.core.config import get_settings
from app.db.session import session_scope
from app.domain import members as members_mod
from app.domain.members import VALID_ROLES

router = APIRouter(tags=["members"])


# ---------------------------------------------------------------------------
# Workspace-scoped endpoints
# ---------------------------------------------------------------------------

@router.get("/workspaces/{workspace_id}/members")
async def list_members(
    workspace_id: str, principal: CurrentPrincipal
) -> list[dict]:
    if principal.workspace_id != workspace_id:
        raise HTTPException(403, "not authorized for this workspace")
    async with session_scope(
        workspace_id=workspace_id, user_id=principal.user_id
    ) as session:
        return [asdict(m) for m in await members_mod.list_members(
            session, workspace_id=workspace_id
        )]


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(owner|admin|editor|viewer)$")


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def update_role(
    workspace_id: str, user_id: str, payload: RoleUpdate
) -> dict:
    async with session_scope(workspace_id=workspace_id) as session:
        ok = await members_mod.update_member_role(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            role=payload.role,
        )
    if not ok:
        raise HTTPException(404, "member not found")
    return {"status": "ok"}


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def remove_member(workspace_id: str, user_id: str) -> None:
    async with session_scope(workspace_id=workspace_id) as session:
        ok = await members_mod.remove_member(
            session, workspace_id=workspace_id, user_id=user_id
        )
    if not ok:
        raise HTTPException(404, "member not found")


# ---------------------------------------------------------------------------
# Invites (create / list / revoke)
# ---------------------------------------------------------------------------

class InviteCreate(BaseModel):
    role: str = Field(pattern="^(admin|editor|viewer)$")
    invited_email: EmailStr | None = None
    ttl_days: int = Field(default=14, ge=1, le=90)


@router.post(
    "/workspaces/{workspace_id}/invites",
    status_code=201,
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def create_invite(
    workspace_id: str, payload: InviteCreate, principal: CurrentPrincipal
) -> dict:
    async with session_scope(
        workspace_id=workspace_id, user_id=principal.user_id
    ) as session:
        invite = await members_mod.create_invite(
            session,
            workspace_id=workspace_id,
            invited_by=principal.user_id,
            role=payload.role,
            invited_email=payload.invited_email,
            ttl_days=payload.ttl_days,
        )
    # Build the accept URL using PUBLIC_BASE_URL → web origin derived from
    # CORS_ORIGINS (the web lives on the same deploy). Fallback to the
    # token only — the UI knows how to construct the URL itself.
    settings = get_settings()
    # web origin = first CORS origin (convention used by /api/auth/token too)
    web_origin = (
        settings.cors_origins_list[0]
        if settings.cors_origins_list
        else settings.public_base_url
    )
    return {
        **asdict(invite),
        "url": f"{web_origin.rstrip('/')}/invite/{invite.token}",
    }


@router.get(
    "/workspaces/{workspace_id}/invites",
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def list_invites(workspace_id: str) -> list[dict]:
    async with session_scope(workspace_id=workspace_id) as session:
        return [
            asdict(i)
            for i in await members_mod.list_invites(
                session, workspace_id=workspace_id
            )
        ]


@router.delete(
    "/workspaces/{workspace_id}/invites/{invite_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def revoke_invite(workspace_id: str, invite_id: str) -> None:
    async with session_scope(workspace_id=workspace_id) as session:
        ok = await members_mod.revoke_invite(
            session, workspace_id=workspace_id, invite_id=invite_id
        )
    if not ok:
        raise HTTPException(404, "invite not found or already handled")


# ---------------------------------------------------------------------------
# Accept invite — public-ish (requires auth, not workspace membership)
# ---------------------------------------------------------------------------

@router.get("/invites/{token}/preview")
async def preview_invite(token: str, principal: CurrentPrincipal) -> dict:
    """Preview what the invite is for. No workspace scoping — we're
    reading from workspace_invite by token, which is its own
    authorization boundary.
    """
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot accept invites")
    async with session_scope() as session:
        preview = await members_mod.preview_invite(session, token=token)
    if not preview:
        raise HTTPException(404, "invite not found, expired, or revoked")
    return asdict(preview)


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, principal: CurrentPrincipal) -> dict:
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot accept invites")
    async with session_scope() as session:
        workspace_id = await members_mod.accept_invite(
            session, token=token, user_id=principal.user_id
        )
    if not workspace_id:
        raise HTTPException(404, "invite not found, expired, or revoked")
    return {"workspace_id": workspace_id}


# Keep VALID_ROLES exported for a future /roles list endpoint.
_ = VALID_ROLES
