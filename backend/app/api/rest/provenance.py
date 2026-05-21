"""W3C PROV-O provenance endpoints.

GET /api/provenance/edge/:id
GET /api/provenance/episode/:id

Returns JSON-LD documents the caller can paste into a PROV-O tool
without translation. RLS scopes reads to the principal's workspace.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.auth.deps import CurrentPrincipal, DbSession
from app.domain import provenance as prov_mod

router = APIRouter(prefix="/provenance", tags=["provenance"])


@router.get("/edge/{edge_id}")
async def edge_provenance(
    edge_id: str, principal: CurrentPrincipal, session: DbSession
) -> dict[str, Any]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    doc = await prov_mod.get_edge_provenance(session, edge_id, principal=principal)
    if not doc:
        raise HTTPException(404, "edge not found")
    return doc


@router.get("/episode/{episode_id}")
async def episode_provenance(
    episode_id: str, principal: CurrentPrincipal, session: DbSession
) -> dict[str, Any]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    doc = await prov_mod.get_episode_provenance(session, episode_id, principal=principal)
    if not doc:
        raise HTTPException(404, "episode not found")
    return doc
