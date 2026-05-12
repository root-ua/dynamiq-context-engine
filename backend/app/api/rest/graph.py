from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.api.rest.schemas import GraphEdgeOut, GraphNodeOut, GraphOut, GraphTraverseIn
from app.auth.deps import CurrentPrincipal, DbSession
from app.retrieval.graph import traverse

router = APIRouter(prefix="/graph", tags=["graph"])


@router.post("/traverse")
async def traverse_route(
    payload: GraphTraverseIn, principal: CurrentPrincipal, session: DbSession,
) -> GraphOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    sub = await traverse(
        session,
        workspace_id=principal.workspace_id,
        seeds=payload.seeds,
        max_hops=payload.max_hops,
        direction=payload.direction,
        predicate_slugs=payload.predicates,
        type_slugs=payload.types,
        as_of_valid=payload.as_of_valid.isoformat() if payload.as_of_valid else None,
        max_nodes=payload.max_nodes,
        principal=principal,
    )
    return GraphOut(
        nodes=[GraphNodeOut(**asdict(n)) for n in sub.nodes],
        edges=[GraphEdgeOut(**asdict(e)) for e in sub.edges],
    )
