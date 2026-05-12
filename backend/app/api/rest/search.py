from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.rest.schemas import SearchHit, SearchIn, SearchOut
from app.auth.deps import CurrentPrincipal, DbSession
from app.retrieval.hybrid import search as hybrid_search

router = APIRouter(tags=["search"])


@router.post("/search")
async def search_route(
    payload: SearchIn, principal: CurrentPrincipal, session: DbSession,
) -> SearchOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    hits = await hybrid_search(
        session,
        workspace_id=principal.workspace_id,
        query=payload.query,
        limit=payload.limit,
        include_kinds=tuple(payload.include_kinds),
        entity_type=payload.entity_type,
        as_of_valid=payload.as_of_valid.isoformat() if payload.as_of_valid else None,
        graph_expand=payload.graph_expand,
        principal=principal,
    )
    return SearchOut(
        query=payload.query,
        hits=[SearchHit(**h.__dict__) for h in hits],
    )
