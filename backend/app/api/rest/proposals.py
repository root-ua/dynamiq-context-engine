"""REST endpoints for the fact review queue + per-class extraction policy.

GET    /api/proposals?status=pending|approved|rejected
GET    /api/proposals/:id
POST   /api/proposals/:id/approve   { comment?: string }
POST   /api/proposals/:id/reject    { reason: string }

GET    /api/extraction-policies
POST   /api/extraction-policies     { entity_type_id?, relation_type_id?, min_confidence, auto_reject_below }
DELETE /api/extraction-policies/:id

All endpoints require a workspace selection (the standard
``CurrentPrincipal`` dep). Approve/reject require editor or above —
reviewers should not be viewers.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, DbSession, require_workspace_role
from app.domain import proposals as proposals_mod
from app.domain.proposals import ProposalError

router = APIRouter()


# ---------------------------------------------------------------------------
# /api/proposals
# ---------------------------------------------------------------------------

proposals_router = APIRouter(prefix="/proposals", tags=["proposals"])


class ApproveBody(BaseModel):
    comment: str | None = None


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class BulkApproveBody(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=500)
    comment: str | None = None


class BulkRejectBody(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=500)
    reason: str = Field(..., min_length=1, max_length=2000)


@proposals_router.get("")
async def list_(
    principal: CurrentPrincipal,
    session: DbSession,
    status: str = Query("pending", pattern="^(pending|approved|rejected|superseded)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    predicate_id: str | None = None,
    source_kind: str | None = None,
) -> list[dict[str, Any]]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    rows = await proposals_mod.list_proposals(
        session,
        workspace_id=principal.workspace_id,
        status=status,
        limit=limit,
        offset=offset,
        predicate_id=predicate_id,
        source_kind=source_kind,
    )
    return [asdict(r) for r in rows]


@proposals_router.get("/{proposal_id}")
async def get_one(
    proposal_id: str, principal: CurrentPrincipal, session: DbSession
) -> dict[str, Any]:
    row = await proposals_mod.get_proposal(session, proposal_id)
    if not row:
        raise HTTPException(404, "proposal not found")
    return asdict(row)


@proposals_router.post("/{proposal_id}/approve")
async def approve(
    proposal_id: str,
    body: ApproveBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, Any]:
    try:
        edge = await proposals_mod.approve_proposal(
            session,
            proposal_id=proposal_id,
            principal_user_id=principal.user_id,
            comment=body.comment,
        )
    except ProposalError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"approved_edge_id": edge.id, "edge": asdict(edge)}


@proposals_router.post("/{proposal_id}/reject")
async def reject(
    proposal_id: str,
    body: RejectBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, Any]:
    try:
        rejected = await proposals_mod.reject_proposal(
            session,
            proposal_id=proposal_id,
            principal_user_id=principal.user_id,
            reason=body.reason,
        )
    except ProposalError as exc:
        raise HTTPException(400, str(exc)) from exc
    return asdict(rejected)


@proposals_router.post("/bulk-approve")
async def bulk_approve(
    body: BulkApproveBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for pid in body.ids:
        try:
            edge = await proposals_mod.approve_proposal(
                session,
                proposal_id=pid,
                principal_user_id=principal.user_id,
                comment=body.comment,
            )
            results.append(
                {"id": pid, "ok": True, "approved_edge_id": edge.id}
            )
        except ProposalError as exc:
            results.append({"id": pid, "ok": False, "error": str(exc)})
    return {"results": results}


@proposals_router.post("/bulk-reject")
async def bulk_reject(
    body: BulkRejectBody,
    session: DbSession,
    principal=Depends(require_workspace_role("editor", "admin", "owner")),
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for pid in body.ids:
        try:
            await proposals_mod.reject_proposal(
                session,
                proposal_id=pid,
                principal_user_id=principal.user_id,
                reason=body.reason,
            )
            results.append({"id": pid, "ok": True})
        except ProposalError as exc:
            results.append({"id": pid, "ok": False, "error": str(exc)})
    return {"results": results}


# ---------------------------------------------------------------------------
# /api/extraction-policies
# ---------------------------------------------------------------------------

policies_router = APIRouter(prefix="/extraction-policies", tags=["proposals"])


class PolicyUpsertBody(BaseModel):
    entity_type_id: str | None = None
    relation_type_id: str | None = None
    min_confidence: float = Field(..., ge=0.0, le=1.0)
    auto_reject_below: float = Field(..., ge=0.0, le=1.0)


@policies_router.get("")
async def list_policies(
    principal: CurrentPrincipal, session: DbSession
) -> list[dict[str, Any]]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    return await proposals_mod.list_policies(session, workspace_id=principal.workspace_id)


@policies_router.post("", status_code=201)
async def upsert(
    body: PolicyUpsertBody,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, str]:
    if body.auto_reject_below > body.min_confidence:
        raise HTTPException(400, "auto_reject_below must be <= min_confidence")
    try:
        policy_id = await proposals_mod.upsert_policy(
            session,
            workspace_id=principal.workspace_id,
            entity_type_id=body.entity_type_id,
            relation_type_id=body.relation_type_id,
            min_confidence=body.min_confidence,
            auto_reject_below=body.auto_reject_below,
        )
    except ProposalError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": policy_id}


@policies_router.delete("/{policy_id}", status_code=204)
async def delete(
    policy_id: str,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> None:
    ok = await proposals_mod.delete_policy(session, policy_id=policy_id)
    if not ok:
        raise HTTPException(404, "policy not found")


# Combined router so __init__.py can include just one.
router.include_router(proposals_router)
router.include_router(policies_router)
