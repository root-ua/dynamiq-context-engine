from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text

from app.api.content_negotiation import accept_jsonld
from app.api.rest.schemas import (
    EntityTypeCreate,
    EntityTypeOut,
    EntityTypeUpdate,
    OntologyProposeIn,
    OntologySnapshotOut,
    RelationTypeCreate,
    RelationTypeOut,
    RelationTypeUpdate,
)
from app.auth.deps import CurrentPrincipal, DbSession
from app.domain import auto_ontology
from app.domain import ontology as ontology_mod
from app.domain.ontology import OntologyError
from app.jsonld import (
    BASE_CONTEXT,
    to_jsonld_relation,
    to_jsonld_type,
)

router = APIRouter(prefix="/ontology", tags=["ontology"])


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

@router.get("/snapshot", response_model_by_alias=True)
async def snapshot(
    _: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | OntologySnapshotOut:
    snap = await ontology_mod.snapshot(session)
    if jsonld:
        doc: dict[str, Any] = dict(BASE_CONTEXT)
        doc["@graph"] = [
            to_jsonld_type(t, snapshot=snap, embed_context=False)
            for t in snap.types
        ] + [
            to_jsonld_relation(r, snapshot=snap, embed_context=False)
            for r in snap.relations
        ]
        return doc
    return OntologySnapshotOut(
        types=[_type_out(t) for t in snap.types],
        relations=[_relation_out(r) for r in snap.relations],
    )


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------

@router.get("/types", response_model_by_alias=True)
async def list_types(
    _: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | list[EntityTypeOut]:
    types = await ontology_mod.list_entity_types(session)
    if jsonld:
        snap = await ontology_mod.snapshot(session)
        doc: dict[str, Any] = dict(BASE_CONTEXT)
        doc["@graph"] = [
            to_jsonld_type(t, snapshot=snap, embed_context=False)
            for t in types
        ]
        return doc
    return [_type_out(t) for t in types]


@router.post("/types", status_code=201, response_model_by_alias=True)
async def create_type(
    payload: EntityTypeCreate, principal: CurrentPrincipal, session: DbSession,
) -> EntityTypeOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    try:
        t = await ontology_mod.create_entity_type(
            session,
            workspace_id=principal.workspace_id,
            name=payload.name,
            slug=payload.slug,
            extends=payload.extends,
            schema=payload.json_schema,
            ui_hints=payload.ui_hints,
            description=payload.description,
            system=payload.system,
        )
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _type_out(t)


@router.get("/types/{ref}", response_model_by_alias=True)
async def get_type(
    ref: str,
    _: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | EntityTypeOut:
    t = await ontology_mod.get_entity_type(session, ref)
    if not t:
        raise HTTPException(404, "entity type not found")
    if jsonld:
        snap = await ontology_mod.snapshot(session)
        return to_jsonld_type(t, snapshot=snap)
    return _type_out(t)


@router.patch("/types/{ref}", response_model_by_alias=True)
async def update_type(
    ref: str,
    payload: EntityTypeUpdate,
    _: CurrentPrincipal,
    session: DbSession,
) -> EntityTypeOut:
    t = await ontology_mod.get_entity_type(session, ref)
    if not t:
        raise HTTPException(404, "entity type not found")
    try:
        updated = await ontology_mod.update_entity_type(
            session,
            type_id=t.id,
            name=payload.name,
            schema=payload.json_schema,
            ui_hints=payload.ui_hints,
            description=payload.description,
            extends=payload.extends if payload.extends is not None else "__unset__",
        )
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _type_out(updated)


@router.delete("/types/{ref}", status_code=204, response_class=Response)
async def delete_type(ref: str, _: CurrentPrincipal, session: DbSession):
    t = await ontology_mod.get_entity_type(session, ref)
    if not t:
        return
    try:
        await ontology_mod.delete_entity_type(session, t.id)
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------------------------------------------------------------------------
# Relation types
# ---------------------------------------------------------------------------

@router.get("/relations")
async def list_relations(
    _: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | list[RelationTypeOut]:
    relations = await ontology_mod.list_relation_types(session)
    if jsonld:
        snap = await ontology_mod.snapshot(session)
        doc: dict[str, Any] = dict(BASE_CONTEXT)
        doc["@graph"] = [
            to_jsonld_relation(r, snapshot=snap, embed_context=False)
            for r in relations
        ]
        return doc
    return [_relation_out(r) for r in relations]


@router.post("/relations", status_code=201)
async def create_relation(
    payload: RelationTypeCreate, principal: CurrentPrincipal, session: DbSession,
) -> RelationTypeOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    try:
        r = await ontology_mod.create_relation_type(
            session,
            workspace_id=principal.workspace_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            domain=payload.domain,
            range_=payload.range,
            cardinality_subject=payload.cardinality_subject,
            cardinality_object=payload.cardinality_object,
            inverse_of=payload.inverse_of,
            symmetric=payload.symmetric,
            transitive=payload.transitive,
            temporal=payload.temporal,
            high_stakes=payload.high_stakes,
            ui_hints=payload.ui_hints,
            system=payload.system,
        )
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _relation_out(r)


@router.get("/relations/{ref}")
async def get_relation(ref: str, _: CurrentPrincipal, session: DbSession) -> RelationTypeOut:
    r = await ontology_mod.get_relation_type(session, ref)
    if not r:
        raise HTTPException(404, "relation type not found")
    return _relation_out(r)


@router.patch("/relations/{ref}")
async def update_relation(
    ref: str,
    payload: RelationTypeUpdate,
    _: CurrentPrincipal,
    session: DbSession,
) -> RelationTypeOut:
    r = await ontology_mod.get_relation_type(session, ref)
    if not r:
        raise HTTPException(404, "relation type not found")
    try:
        updated = await ontology_mod.update_relation_type(
            session,
            relation_id=r.id,
            **{k: v for k, v in payload.model_dump(exclude_none=True).items() if k != "range"},
            range_=payload.range,
        )
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _relation_out(updated)


@router.delete("/relations/{ref}", status_code=204, response_class=Response)
async def delete_relation(ref: str, _: CurrentPrincipal, session: DbSession):
    r = await ontology_mod.get_relation_type(session, ref)
    if not r:
        return
    try:
        await ontology_mod.delete_relation_type(session, r.id)
    except OntologyError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------------------------------------------------------------------------
# AI propose
# ---------------------------------------------------------------------------

@router.post("/propose")
async def propose(
    payload: OntologyProposeIn,
    principal: CurrentPrincipal,
    session: DbSession,
):
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    samples = list(payload.samples or [])
    if payload.episode_ids:
        result = await session.execute(
            text(
                "SELECT content_text FROM episode WHERE id = ANY(:ids)"
            ),
            {"ids": payload.episode_ids},
        )
        samples.extend([r[0] for r in result if r[0]])

    if not samples:
        raise HTTPException(400, "provide at least one sample or episode_ids")

    proposal = await auto_ontology.propose_ontology(
        session, workspace_id=principal.workspace_id, samples=samples,
    )

    if payload.apply:
        applied = await auto_ontology.apply_proposal(
            session,
            workspace_id=principal.workspace_id,
            proposal=proposal,
            actor_id=principal.user_id,
        )
        return {"proposal": proposal.model_dump(), "applied": asdict(applied)}

    return {"proposal": proposal.model_dump()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_out(t: ontology_mod.EntityType) -> EntityTypeOut:
    return EntityTypeOut.model_validate({
        "id": t.id, "workspace_id": t.workspace_id, "name": t.name, "slug": t.slug,
        "extends_id": t.extends_id, "hierarchy": t.hierarchy, "schema": t.schema,
        "ui_hints": t.ui_hints, "description": t.description, "system": t.system,
    })


def _relation_out(r: ontology_mod.RelationType) -> RelationTypeOut:
    return RelationTypeOut(
        id=r.id, workspace_id=r.workspace_id, name=r.name, slug=r.slug,
        description=r.description,
        domain_type_id=r.domain_type_id, range_type_id=r.range_type_id,
        cardinality_subject=r.cardinality_subject,
        cardinality_object=r.cardinality_object,
        inverse_of_id=r.inverse_of_id,
        symmetric=r.symmetric, transitive=r.transitive,
        temporal=r.temporal, high_stakes=r.high_stakes,
        ui_hints=r.ui_hints, system=r.system,
    )
