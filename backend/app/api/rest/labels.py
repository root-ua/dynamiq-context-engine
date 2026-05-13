"""Sensitivity labels + label policy endpoints.

GET    /api/labels
POST   /api/labels             { slug, name, description?, color?, parent_slug? }
DELETE /api/labels/:slug
POST   /api/labels/:slug/assign     { target_kind, target_id }
POST   /api/labels/:slug/unassign   { target_kind, target_id }

GET    /api/label-policies
POST   /api/label-policies     { name, rule, action, enabled? }
DELETE /api/label-policies/:id

All write endpoints require ``admin`` or ``owner`` workspace role.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, DbSession, require_workspace_role
from app.domain import sensitivity as sens_mod

router = APIRouter()


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

labels_router = APIRouter(prefix="/labels", tags=["labels"])


class LabelCreateBody(BaseModel):
    slug: str = Field(..., min_length=1, max_length=80)
    name: str
    description: str | None = None
    color: str | None = None
    parent_slug: str | None = None


class LabelAssignBody(BaseModel):
    target_kind: str = Field(..., pattern="^(edge|episode)$")
    target_id: str


@labels_router.get("")
async def list_(principal: CurrentPrincipal, session: DbSession) -> list[dict[str, Any]]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    return [asdict(label) for label in await sens_mod.list_labels(
        session, workspace_id=principal.workspace_id
    )]


@labels_router.get("/for/{target_kind}/{target_id}")
async def labels_for(
    target_kind: str,
    target_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> list[dict[str, Any]]:
    if target_kind not in ("edge", "episode"):
        raise HTTPException(400, "invalid target_kind")
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    rows = await sens_mod.labels_for(
        session, target_kind=target_kind, target_id=target_id
    )
    return [asdict(r) for r in rows]


@labels_router.post("", status_code=201)
async def create(
    body: LabelCreateBody,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, Any]:
    label = await sens_mod.create_label(
        session,
        workspace_id=principal.workspace_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        color=body.color,
        parent_slug=body.parent_slug,
    )
    return asdict(label)


@labels_router.delete("/{slug}", status_code=204)
async def delete(
    slug: str,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> None:
    ok = await sens_mod.delete_label(
        session, workspace_id=principal.workspace_id, slug=slug
    )
    if not ok:
        raise HTTPException(404, "label not found")


@labels_router.post("/{slug}/assign")
async def assign(
    slug: str,
    body: LabelAssignBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, str]:
    await sens_mod.assign_label(
        session,
        workspace_id=principal.workspace_id,
        target_kind=body.target_kind,
        target_id=body.target_id,
        label_slug=slug,
        assigned_by=principal.user_id,
    )
    return {"ok": "true"}


@labels_router.post("/{slug}/unassign")
async def unassign(
    slug: str,
    body: LabelAssignBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, str]:
    ok = await sens_mod.unassign_label(
        session,
        workspace_id=principal.workspace_id,
        target_kind=body.target_kind,
        target_id=body.target_id,
        label_slug=slug,
    )
    if not ok:
        raise HTTPException(404, "assignment not found")
    return {"ok": "true"}


class BulkAssignTarget(BaseModel):
    kind: str = Field(..., pattern="^(edge|episode)$")
    id: str


class BulkAssignBody(BaseModel):
    targets: list[BulkAssignTarget] = Field(..., min_length=1, max_length=500)


@labels_router.post("/{slug}/bulk-assign")
async def bulk_assign(
    slug: str,
    body: BulkAssignBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, Any]:
    assigned = 0
    failed: list[dict[str, str]] = []
    for t in body.targets:
        try:
            await sens_mod.assign_label(
                session,
                workspace_id=principal.workspace_id,
                target_kind=t.kind,
                target_id=t.id,
                label_slug=slug,
                assigned_by=principal.user_id,
            )
            assigned += 1
        except Exception as exc:
            failed.append({"id": t.id, "error": str(exc)})
    return {"assigned": assigned, "failed": failed}


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

policies_router = APIRouter(prefix="/label-policies", tags=["labels"])


class PolicyCreateBody(BaseModel):
    name: str
    rule: dict[str, Any]
    action: str = Field(..., pattern="^(drop|warn|block)$")
    enabled: bool = True


@policies_router.get("")
async def list_policies(
    principal: CurrentPrincipal, session: DbSession
) -> list[dict[str, Any]]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    return [asdict(p) for p in await sens_mod.list_policies(
        session, workspace_id=principal.workspace_id
    )]


@policies_router.post("", status_code=201)
async def create_policy(
    body: PolicyCreateBody,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, Any]:
    policy = await sens_mod.create_policy(
        session,
        workspace_id=principal.workspace_id,
        name=body.name,
        rule=body.rule,
        action=body.action,
        enabled=body.enabled,
    )
    return asdict(policy)


@policies_router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: str,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> None:
    ok = await sens_mod.delete_policy(session, policy_id=policy_id)
    if not ok:
        raise HTTPException(404, "policy not found")


router.include_router(labels_router)
router.include_router(policies_router)
