from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.api.content_negotiation import accept_jsonld
from app.api.rest.schemas import EdgeCreate, EdgeInvalidate, EdgeOut
from app.auth.deps import CurrentPrincipal, DbSession
from app.domain import edge as edge_mod
from app.domain import ontology as ontology_mod
from app.domain.edge import EdgeError
from app.domain.ontology import OntologyError
from app.jsonld import to_jsonld_edge

router = APIRouter(prefix="/edges", tags=["edges"])


@router.get("/time-bounds")
async def time_bounds(
    principal: CurrentPrincipal, session: DbSession
) -> dict[str, str | None]:
    """Return the earliest + latest valid_time in the workspace's edges.

    Used by the graph's time slider to pick its range endpoints without
    having to paginate every edge. The RLS policy scopes the query to
    the principal's workspace automatically.
    """
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    # The slider's range needs to span the earliest fact start to at
    # least "now" — and ideally further if the workspace has future-dated
    # facts (e.g. "Beacon MVP ships 2026-08-15" creates an edge with
    # valid_from in the future).
    #
    # CRITICAL: upper(valid_time) is 'infinity'::timestamptz for open-ended
    # facts (most of them). MAX over a column containing infinity yields
    # infinity, which the frontend can't parse as a date. Strip infinity
    # to NULL before the MAX with a CASE WHEN.
    result = await session.execute(
        text(
            """
            SELECT
              MIN(lower(valid_time))::text AS min_valid_from,
              GREATEST(
                MAX(CASE
                  WHEN upper(valid_time) = 'infinity'::timestamptz THEN NULL
                  ELSE upper(valid_time)
                END),
                MAX(lower(valid_time)),
                now()
              )::text AS max_valid_from
            FROM edge
            WHERE upper(sys_time) = 'infinity'::timestamptz
            """
        ),
    )
    row = result.mappings().first()
    return {
        "min_valid_from": row["min_valid_from"] if row else None,
        "max_valid_from": row["max_valid_from"] if row else None,
    }


@router.post("", status_code=201)
async def create(
    payload: EdgeCreate, principal: CurrentPrincipal, session: DbSession,
) -> EdgeOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    try:
        edge = await edge_mod.add_fact(
            session,
            workspace_id=principal.workspace_id,
            subject_id=payload.subject_id,
            predicate=payload.predicate,
            object_id=payload.object_id,
            fact=payload.fact,
            props=payload.props,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            source_id=payload.source_id,
            source_kind=payload.source_kind,
            confidence=payload.confidence,
            created_by=principal.user_id,
        )
    except (OntologyError, EdgeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return EdgeOut(**asdict(edge))


@router.get("/{edge_id}")
async def get(
    edge_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | EdgeOut:
    edge = await edge_mod.get(session, edge_id, principal=principal)
    if not edge:
        raise HTTPException(404, "edge not found")
    if jsonld:
        snapshot = await ontology_mod.snapshot(session)
        return to_jsonld_edge(edge, snapshot=snapshot)
    return EdgeOut(**asdict(edge))


@router.post("/{edge_id}/invalidate")
async def invalidate(
    edge_id: str,
    payload: EdgeInvalidate,
    principal: CurrentPrincipal,
    session: DbSession,
) -> EdgeOut:
    try:
        edge = await edge_mod.invalidate(
            session,
            edge_id=edge_id,
            invalidated_at=payload.invalidated_at,
            reason=payload.reason,
            actor_kind="user",
            actor_id=principal.user_id,
        )
    except EdgeError as exc:
        raise HTTPException(404, str(exc)) from exc
    return EdgeOut(**asdict(edge))


@router.get("")
async def list_live(
    principal: CurrentPrincipal,
    session: DbSession,
    subject_id: str | None = Query(default=None),
    object_id: str | None = Query(default=None),
    predicate: str | None = Query(default=None),
    as_of_valid: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[EdgeOut]:
    if as_of_valid:
        items = await edge_mod.as_of(
            session, valid_at=as_of_valid,
            subject_id=subject_id, object_id=object_id, predicate=predicate,
            limit=limit, principal=principal,
        )
    else:
        items = await edge_mod.live_edges(
            session, subject_id=subject_id, object_id=object_id,
            predicate=predicate, limit=limit, principal=principal,
        )
    return [EdgeOut(**asdict(e)) for e in items]
