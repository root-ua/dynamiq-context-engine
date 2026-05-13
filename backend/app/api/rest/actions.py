"""Kinetic action layer REST endpoints.

GET    /api/action-types
POST   /api/action-types                       (admin/owner)
POST   /api/actions/:type_slug/invoke          { input, idempotency_key }
GET    /api/actions/invocations[?status=]
POST   /api/actions/invocations/:id/approve    (admin/owner)
POST   /api/actions/invocations/:id/reject     (admin/owner)  { reason }
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, DbSession, require_workspace_role
from app.domain import action as action_mod
from app.domain.action import ActionError

router = APIRouter()


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

types_router = APIRouter(prefix="/action-types", tags=["actions"])


class ActionTypeCreateBody(BaseModel):
    slug: str
    name: str
    description: str | None = None
    source_kind: str | None = None
    input_schema: dict[str, Any]
    required_role: str = Field("editor", pattern="^(viewer|editor|admin|owner)$")
    idempotency_required: bool = True
    requires_approval: bool = False
    side_effects: list[str] = Field(default_factory=list)


@types_router.get("")
async def list_types(
    principal: CurrentPrincipal, session: DbSession
) -> list[dict[str, Any]]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    return [asdict(t) for t in await action_mod.list_action_types(
        session, workspace_id=principal.workspace_id
    )]


@types_router.post("", status_code=201)
async def create_type(
    body: ActionTypeCreateBody,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, Any]:
    a = await action_mod.register_action_type(
        session,
        workspace_id=principal.workspace_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        source_kind=body.source_kind,
        input_schema=body.input_schema,
        required_role=body.required_role,
        idempotency_required=body.idempotency_required,
        requires_approval=body.requires_approval,
        side_effects=body.side_effects,
    )
    return asdict(a)


# ---------------------------------------------------------------------------
# Invocations
# ---------------------------------------------------------------------------

invocations_router = APIRouter(prefix="/actions", tags=["actions"])


class InvokeBody(BaseModel):
    input: dict[str, Any]
    idempotency_key: str | None = None


@invocations_router.post("/{type_slug}/invoke")
async def invoke(
    type_slug: str,
    body: InvokeBody,
    session: DbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    key = body.idempotency_key or str(uuid4())
    try:
        inv = await action_mod.execute_action(
            session,
            workspace_id=principal.workspace_id,
            type_slug=type_slug,
            input=body.input,
            idempotency_key=key,
            principal=principal,
        )
    except ActionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return asdict(inv)


@invocations_router.get("/invocations")
async def list_invs(
    principal: CurrentPrincipal,
    session: DbSession,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    rows = await action_mod.list_invocations(
        session,
        workspace_id=principal.workspace_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [asdict(r) for r in rows]


@invocations_router.post("/invocations/{invocation_id}/approve")
async def approve(
    invocation_id: str,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, Any]:
    try:
        result = await action_mod.approve_invocation(
            session, invocation_id=invocation_id, principal=principal
        )
    except ActionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return asdict(result)


class RejectInvBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


@invocations_router.post("/invocations/{invocation_id}/reject")
async def reject(
    invocation_id: str,
    body: RejectInvBody,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, Any]:
    try:
        result = await action_mod.reject_invocation(
            session,
            invocation_id=invocation_id,
            principal=principal,
            reason=body.reason,
        )
    except ActionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return asdict(result)


router.include_router(types_router)
router.include_router(invocations_router)
