from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app.api.content_negotiation import accept_jsonld
from app.api.rest.schemas import (
    EdgeOut,
    EntityCreate,
    EntityMergeIn,
    EntityOut,
    EntityUpdate,
)
from app.auth.acl import edge_visibility_clause
from app.auth.deps import CurrentPrincipal, DbSession
from app.auth.external_acl import resolve_user_identities
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import entity_resolver as resolver_mod
from app.domain import ontology as ontology_mod
from app.domain.document import backlinks_for_entity
from app.domain.ontology import OntologyError
from app.jsonld import to_jsonld_entity

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("")
async def list_entities(
    principal: CurrentPrincipal,
    session: DbSession,
    type: str | None = Query(default=None),
    query: str | None = Query(default=None),
    include_subtypes: bool = Query(default=True),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
) -> list[EntityOut]:
    items = await entity_mod.list_entities(
        session, type_ref=type, query=query,
        include_subtypes=include_subtypes,
        limit=limit, offset=offset,
    )
    if principal.kind == "user":
        visible = await _filter_visible_entity_ids(
            session, [i.id for i in items], principal
        )
        items = [i for i in items if i.id in visible]
    return [EntityOut(**asdict(i)) for i in items]


@router.post("", status_code=201)
async def create(
    payload: EntityCreate, principal: CurrentPrincipal, session: DbSession,
) -> EntityOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    try:
        created = await entity_mod.create(
            session,
            workspace_id=principal.workspace_id,
            type_ref=payload.type,
            canonical=payload.canonical,
            aliases=payload.aliases,
            summary=payload.summary,
            props=payload.props,
            created_by=principal.user_id,
        )
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return EntityOut(**asdict(created))


@router.get("/{ref}")
async def get(
    ref: str,
    principal: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | EntityOut:
    ent = await entity_mod.get(session, ref)
    if not ent:
        raise HTTPException(404, "entity not found")
    # 404 (not 403) for ACL-hidden entities to avoid leaking existence.
    if principal.kind == "user":
        visible = await _filter_visible_entity_ids(session, [ent.id], principal)
        if ent.id not in visible:
            raise HTTPException(404, "entity not found")
    if jsonld:
        snapshot = await ontology_mod.snapshot(session)
        refs = await resolver_mod.list_external_refs(session, entity_id=ent.id)
        external_refs = [(r["kind"], r["value"]) for r in refs]
        return to_jsonld_entity(
            ent, snapshot=snapshot, external_refs=external_refs,
        )
    return EntityOut(**asdict(ent))


@router.patch("/{ref}")
async def update(
    ref: str,
    payload: EntityUpdate,
    _: CurrentPrincipal,
    session: DbSession,
) -> EntityOut:
    ent = await entity_mod.get(session, ref)
    if not ent:
        raise HTTPException(404, "entity not found")
    patch: dict[str, Any] = {}
    if payload.canonical is not None:
        patch["canonical"] = payload.canonical
    if payload.aliases is not None:
        patch["aliases"] = payload.aliases
    if payload.summary is not None:
        patch["summary"] = payload.summary
    if payload.props is not None:
        patch["props"] = payload.props
    try:
        updated = await entity_mod.update(session, entity_id=ent.id, patch=patch)
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return EntityOut(**asdict(updated))


@router.delete("/{ref}", status_code=204, response_class=Response)
async def delete(ref: str, _: CurrentPrincipal, session: DbSession):
    ent = await entity_mod.get(session, ref)
    if not ent:
        return
    await entity_mod.soft_delete(session, ent.id)


@router.get("/{ref}/edges")
async def edges(
    ref: str,
    principal: CurrentPrincipal,
    session: DbSession,
    direction: str = Query(default="out", pattern="^(out|in|both)$"),
    predicate: str | None = Query(default=None),
) -> list[EdgeOut]:
    ent = await entity_mod.get(session, ref)
    if not ent:
        raise HTTPException(404, "entity not found")

    items_out: list[EdgeOut] = []
    if direction == "out":
        items = await edge_mod.live_edges(session, subject_id=ent.id, predicate=predicate, principal=principal)
    elif direction == "in":
        items = await edge_mod.live_edges(session, object_id=ent.id, predicate=predicate, principal=principal)
    else:
        out_edges = await edge_mod.live_edges(session, subject_id=ent.id, predicate=predicate, principal=principal)
        in_edges = await edge_mod.live_edges(session, object_id=ent.id, predicate=predicate, principal=principal)
        items = out_edges + in_edges
    items_out = [EdgeOut(**asdict(e)) for e in items]
    return items_out


@router.get("/{ref}/history")
async def history(
    ref: str, principal: CurrentPrincipal, session: DbSession,
    predicate: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
) -> list[EdgeOut]:
    ent = await entity_mod.get(session, ref)
    if not ent:
        raise HTTPException(404, "entity not found")
    items = await edge_mod.history(session, subject_id=ent.id, predicate=predicate, limit=limit, principal=principal)
    inbound = await edge_mod.history(session, object_id=ent.id, predicate=predicate, limit=limit, principal=principal)
    all_edges = {i.id: i for i in items + inbound}
    ordered = sorted(all_edges.values(), key=lambda e: e.sys_from, reverse=True)
    return [EdgeOut(**asdict(e)) for e in ordered[:limit]]


@router.get("/{ref}/backlinks")
async def backlinks(ref: str, _: CurrentPrincipal, session: DbSession):
    ent = await entity_mod.get(session, ref)
    if not ent:
        raise HTTPException(404, "entity not found")
    return await backlinks_for_entity(session, entity_id=ent.id)


@router.post("/{ref}/merge")
async def merge(
    ref: str,
    payload: EntityMergeIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> EntityOut:
    survivor = await entity_mod.get(session, ref)
    loser = await entity_mod.get(session, payload.loser_id)
    if not survivor or not loser:
        raise HTTPException(404, "entity not found")
    result = await entity_mod.merge_entities(
        session,
        survivor_id=survivor.id,
        loser_id=loser.id,
        actor_kind="user",
        actor_id=principal.user_id,
    )
    return EntityOut(**asdict(result))


async def _filter_visible_entity_ids(
    session: DbSession,
    entity_ids: list[str],
    principal: CurrentPrincipal,
) -> set[str]:
    """Return the subset of entity_ids that the caller can see.

    Rule: an entity is visible iff at least one attaching edge is visible.
    An edge is visible iff its source episode passes the source-ACL filter
    (workspace-trust fallback applies when the source episode has no ACL).

    Entities with zero attaching edges are treated as hidden — they only
    arise from extraction where every fact about the entity was rejected
    by the ontology guard. Surfacing them in autocomplete leaks their
    name (the original bug). If a fresh entity-creation flow needs them
    visible, add an exception once we have a real use case.
    """
    if not entity_ids or principal.kind != "user":
        return set(entity_ids)
    identities = await resolve_user_identities(session, principal)
    edge_acl = edge_visibility_clause(
        principal, edge_alias="ed", identities=identities,
    )
    params: dict[str, object] = {"ids": entity_ids}
    for key, value in edge_acl._bindparams.items():
        params[key] = value.value
    rows = await session.execute(
        text(
            f"""
            SELECT DISTINCT ent_id::text AS id FROM (
              SELECT ed.subject_id AS ent_id FROM edge ed
              WHERE ed.subject_id::text = ANY(:ids) AND ({edge_acl.text})
              UNION
              SELECT ed.object_id AS ent_id FROM edge ed
              WHERE ed.object_id::text = ANY(:ids) AND ({edge_acl.text})
            ) AS v
            """
        ),
        params,
    )
    return {r["id"] for r in rows.mappings()}
