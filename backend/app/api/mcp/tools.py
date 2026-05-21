"""MCP tool registry.

Each tool is a thin wrapper around a domain service call, with a
Pydantic input schema used both for JSON-RPC (MCP) and for REST
``/mcp/tools/{name}`` invocations.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import Principal
from app.core.logging import get_logger
from app.domain import action as action_mod
from app.domain import auto_ontology
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain import ontology as ontology_mod
from app.domain import proposals as proposals_mod
from app.domain import provenance as prov_mod
from app.domain import sensitivity as sens_mod
from app.retrieval.graph import traverse
from app.retrieval.hybrid import search as hybrid_search
from app.workers.queue import enqueue_extraction

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class SearchMemoryIn(BaseModel):
    query: str
    limit: int = 20
    entity_type: str | None = None
    include_kinds: list[Literal["entity", "edge", "episode", "block"]] = Field(
        default_factory=lambda: ["entity", "edge", "episode", "block"]
    )
    as_of_valid: datetime | None = None
    graph_expand: bool = False


class GetEntityIn(BaseModel):
    ref: str = Field(..., description="Entity id, IRI, or canonical name.")
    include_edges: bool = True
    include_history: bool = False
    include_backlinks: bool = False


class GraphQueryIn(BaseModel):
    seeds: list[str]
    max_hops: int = 2
    direction: Literal["out", "in", "both"] = "both"
    predicates: list[str] | None = None
    types: list[str] | None = None
    as_of_valid: datetime | None = None


class AddFactIn(BaseModel):
    subject: str = Field(..., description="Entity id, IRI, or canonical name.")
    predicate: str
    object: str
    fact: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float | None = None
    source_ref: str | None = None
    derived_from_activity_ids: list[str] | None = Field(
        default=None,
        description=(
            "Cross-agent provenance. When this agent's fact was inferred "
            "from another agent's prior activity (e.g. a meta-agent "
            "reading traces), pass the upstream activity ids here. Each "
            "is recorded as a prov:wasDerivedFrom link in get_provenance."
        ),
    )


class InvalidateFactIn(BaseModel):
    edge_id: str
    invalidated_at: datetime | None = None
    reason: str | None = None


class AddEpisodeIn(BaseModel):
    content: str
    source_kind: str = "agent"
    source_ref: str | None = None
    occurred_at: datetime | None = None
    extract: bool = True
    derived_from_activity_ids: list[str] | None = Field(
        default=None,
        description=(
            "Cross-agent provenance for episode ingestion. When a meta-agent "
            "creates an episode from another agent's trace, pass the upstream "
            "activity ids so the chain is queryable via get_provenance."
        ),
    )


class UpdateEntityIn(BaseModel):
    ref: str
    canonical: str | None = None
    aliases: list[str] | None = None
    summary: str | None = None
    props: dict[str, Any] | None = None


class OntologyDescribeIn(BaseModel):
    include_schemas: bool = True


class CreateEntityTypeIn(BaseModel):
    name: str
    slug: str | None = None
    extends: str | None = None
    description: str | None = None
    properties: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Each property: {name, label, type: string|number|integer|boolean|date|date-time|enum, enum_values?, required?}",
    )


class CreateRelationTypeIn(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None
    domain: str
    range: str
    cardinality_subject: Literal["one", "many"] = "many"
    cardinality_object: Literal["one", "many"] = "many"
    symmetric: bool = False
    transitive: bool = False
    temporal: bool = True
    high_stakes: bool = False


class ProposeOntologyIn(BaseModel):
    samples: list[str] = Field(default_factory=list)
    episode_ids: list[str] = Field(default_factory=list)
    apply: bool = False


class AsOfIn(BaseModel):
    valid_at: datetime
    subject: str | None = None
    predicate: str | None = None


class GetFactIn(BaseModel):
    subject: str = Field(..., description="Entity id, IRI, or canonical name.")
    predicate: str = Field(..., description="Relation slug or id.")
    object: str | None = Field(
        default=None,
        description="Disambiguate when the subject has multiple values for this predicate.",
    )
    as_of: datetime | None = Field(
        default=None,
        description="Bi-temporal lookup: return the fact that was true at this point in valid-time.",
    )
    require_min_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Refuse the answer if the live edge's confidence is below this threshold.",
    )


class GetProvenanceIn(BaseModel):
    fact_id: str = Field(..., description="Edge id (a.k.a. fact id).")


class ListProposalsIn(BaseModel):
    status: Literal["pending", "approved", "rejected", "superseded"] = "pending"
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)
    predicate_id: str | None = None
    source_kind: str | None = None


class ApproveProposalIn(BaseModel):
    proposal_id: str
    comment: str | None = None


class RejectProposalIn(BaseModel):
    proposal_id: str
    reason: str = Field(..., min_length=1, max_length=2000)


class ListLabelsIn(BaseModel):
    pass


class AssignLabelIn(BaseModel):
    target_kind: Literal["edge", "episode"]
    target_id: str
    label_slug: str


class ListActionTypesIn(BaseModel):
    pass


class ExecuteActionIn(BaseModel):
    type_slug: str
    input: dict[str, Any]
    idempotency_key: str | None = None


class ListActionInvocationsIn(BaseModel):
    status: str | None = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def _search_memory(session: AsyncSession, workspace_id: str, actor_id: str | None, p: SearchMemoryIn, principal: Principal) -> dict[str, Any]:
    hits = await hybrid_search(
        session,
        workspace_id=workspace_id,
        query=p.query,
        limit=p.limit,
        include_kinds=tuple(p.include_kinds),
        entity_type=p.entity_type,
        as_of_valid=p.as_of_valid.isoformat() if p.as_of_valid else None,
        graph_expand=p.graph_expand,
        principal=principal,
    )
    return {"query": p.query, "hits": [h.__dict__ for h in hits]}


async def _get_entity(session: AsyncSession, workspace_id: str, actor_id: str | None, p: GetEntityIn, principal: Principal) -> dict[str, Any]:
    ent = await entity_mod.get(session, p.ref)
    if not ent:
        return {"error": "entity not found"}

    out: dict[str, Any] = {"entity": asdict(ent)}
    if p.include_edges:
        out["edges_out"] = [asdict(e) for e in await edge_mod.live_edges(session, subject_id=ent.id, principal=principal)]
        out["edges_in"] = [asdict(e) for e in await edge_mod.live_edges(session, object_id=ent.id, principal=principal)]
    if p.include_history:
        out["history_out"] = [asdict(e) for e in await edge_mod.history(session, subject_id=ent.id, principal=principal)]
        out["history_in"] = [asdict(e) for e in await edge_mod.history(session, object_id=ent.id, principal=principal)]
    if p.include_backlinks:
        from app.domain.document import backlinks_for_entity
        out["backlinks"] = await backlinks_for_entity(session, entity_id=ent.id)
    return out


async def _graph_query(session: AsyncSession, workspace_id: str, actor_id: str | None, p: GraphQueryIn, principal: Principal) -> dict[str, Any]:
    seed_ids: list[str] = []
    for s in p.seeds:
        resolved = await entity_mod.get(session, s)
        if resolved:
            seed_ids.append(resolved.id)
    if not seed_ids:
        return {"nodes": [], "edges": []}

    sub = await traverse(
        session,
        workspace_id=workspace_id,
        seeds=seed_ids,
        max_hops=p.max_hops,
        direction=p.direction,
        predicate_slugs=p.predicates,
        type_slugs=p.types,
        as_of_valid=p.as_of_valid.isoformat() if p.as_of_valid else None,
        principal=principal,
    )
    return {"nodes": [asdict(n) for n in sub.nodes], "edges": [asdict(e) for e in sub.edges]}


async def _add_fact(
    session: AsyncSession,
    workspace_id: str,
    actor_id: str | None,
    p: AddFactIn,
    principal: Principal,
) -> dict[str, Any]:
    subject = await entity_mod.get(session, p.subject)
    obj = await entity_mod.get(session, p.object)
    if not subject or not obj:
        return {"error": "subject or object not found"}

    # ``prov_activity.agent_kind`` is constrained to
    # {'llm','user','system'} — service-token callers map to 'system';
    # session-JWT callers map to 'user'.
    agent_kind = "system" if principal.kind == "service" else "user"
    activity_id = await prov_mod.start_activity(
        session,
        workspace_id=workspace_id,
        kind="manual_edit",
        agent_kind=agent_kind,
        agent_ref=actor_id,
        inputs={
            "tool": "add_fact",
            "subject": p.subject,
            "predicate": p.predicate,
            "object": p.object,
        },
    )

    # Cross-agent provenance: link this activity to every upstream
    # activity the caller named so ``get_provenance`` walks the chain.
    if p.derived_from_activity_ids:
        for upstream_id in p.derived_from_activity_ids:
            await prov_mod.link_derivation(
                session,
                workspace_id=workspace_id,
                derived_activity_id=activity_id,
                upstream_activity_id=upstream_id,
                kind="derived",
            )

    edge = None
    try:
        edge = await edge_mod.add_fact(
            session,
            workspace_id=workspace_id,
            subject_id=subject.id,
            predicate=p.predicate,
            object_id=obj.id,
            fact=p.fact,
            valid_from=p.valid_from,
            valid_to=p.valid_to,
            confidence=p.confidence,
            source_kind="agent",
            source_id=None,
            created_by=actor_id,
            prov_activity_id=activity_id,
        )
    finally:
        # Always close the activity, even on a domain-layer raise, so we
        # don't leave open ``prov_activity`` rows littering audit views.
        await prov_mod.end_activity(
            session, activity_id,
            outputs={"edge_id": edge.id} if edge else {"error": "raised"},
        )
    return {"edge": asdict(edge)}


async def _invalidate_fact(session: AsyncSession, workspace_id: str, actor_id: str | None, p: InvalidateFactIn) -> dict[str, Any]:
    edge = await edge_mod.invalidate(
        session,
        edge_id=p.edge_id,
        invalidated_at=p.invalidated_at,
        reason=p.reason,
        actor_kind="agent",
        actor_id=actor_id,
    )
    return {"edge": asdict(edge)}


async def _add_episode(
    session: AsyncSession,
    workspace_id: str,
    actor_id: str | None,
    p: AddEpisodeIn,
    principal: Principal,
) -> dict[str, Any]:
    # ``prov_activity.agent_kind`` is constrained to
    # {'llm','user','system'} — service-token callers map to 'system';
    # session-JWT callers map to 'user'.
    agent_kind = "system" if principal.kind == "service" else "user"
    activity_id = await prov_mod.start_activity(
        session,
        workspace_id=workspace_id,
        kind="manual_edit",
        agent_kind=agent_kind,
        agent_ref=actor_id,
        inputs={"tool": "add_episode", "source_kind": p.source_kind},
    )

    if p.derived_from_activity_ids:
        for upstream_id in p.derived_from_activity_ids:
            await prov_mod.link_derivation(
                session,
                workspace_id=workspace_id,
                derived_activity_id=activity_id,
                upstream_activity_id=upstream_id,
                kind="derived",
            )

    ep = None
    try:
        ep = await episode_mod.add_episode(
            session,
            workspace_id=workspace_id,
            content=p.content,
            source_kind=p.source_kind,
            source_ref=p.source_ref,
            occurred_at=p.occurred_at,
            created_by=actor_id,
        )
        # Episode domain layer doesn't accept prov_activity_id today —
        # stamp it post-insert so the MCP wrapper keeps the contract.
        await session.execute(
            text(
                "UPDATE episode SET prov_activity_id = CAST(:a AS uuid) "
                "WHERE id = :id"
            ),
            {"a": activity_id, "id": ep.id},
        )
        if p.extract:
            await enqueue_extraction(
                workspace_id=workspace_id, episode_id=ep.id, actor_id=actor_id,
            )
    finally:
        await prov_mod.end_activity(
            session, activity_id,
            outputs={"episode_id": ep.id} if ep else {"error": "raised"},
        )
    return {"episode_id": ep.id, "status": ep.processing_status}


async def _update_entity(session: AsyncSession, workspace_id: str, actor_id: str | None, p: UpdateEntityIn) -> dict[str, Any]:
    ent = await entity_mod.get(session, p.ref)
    if not ent:
        return {"error": "entity not found"}
    patch: dict[str, Any] = {}
    if p.canonical is not None: patch["canonical"] = p.canonical
    if p.aliases is not None: patch["aliases"] = p.aliases
    if p.summary is not None: patch["summary"] = p.summary
    if p.props is not None: patch["props"] = p.props
    updated = await entity_mod.update(session, entity_id=ent.id, patch=patch)
    return {"entity": asdict(updated)}


async def _ontology_describe(session: AsyncSession, workspace_id: str, actor_id: str | None, p: OntologyDescribeIn) -> dict[str, Any]:
    snap = await ontology_mod.snapshot(session)
    types = []
    for t in snap.types:
        item: dict[str, Any] = {
            "slug": t.slug, "name": t.name, "hierarchy": t.hierarchy,
            "description": t.description, "system": t.system,
        }
        if p.include_schemas:
            item["schema"] = t.schema
        types.append(item)
    relations = [
        {
            "slug": r.slug, "name": r.name, "description": r.description,
            "domain": _slug_by_id(snap, r.domain_type_id),
            "range": _slug_by_id(snap, r.range_type_id),
            "cardinality_subject": r.cardinality_subject,
            "cardinality_object": r.cardinality_object,
            "symmetric": r.symmetric, "transitive": r.transitive,
            "temporal": r.temporal, "high_stakes": r.high_stakes,
        }
        for r in snap.relations
    ]
    return {"types": types, "relations": relations}


async def _create_entity_type(session: AsyncSession, workspace_id: str, actor_id: str | None, p: CreateEntityTypeIn) -> dict[str, Any]:
    schema = _props_to_schema(p.properties)
    t = await ontology_mod.create_entity_type(
        session, workspace_id=workspace_id,
        name=p.name, slug=p.slug, extends=p.extends,
        schema=schema, description=p.description,
        ui_hints={"proposed_by": actor_id or "agent"},
    )
    return {"type": {"id": t.id, "slug": t.slug, "name": t.name,
                     "hierarchy": t.hierarchy, "schema": t.schema}}


async def _create_relation_type(session: AsyncSession, workspace_id: str, actor_id: str | None, p: CreateRelationTypeIn) -> dict[str, Any]:
    r = await ontology_mod.create_relation_type(
        session, workspace_id=workspace_id,
        name=p.name, slug=p.slug, description=p.description,
        domain=p.domain, range_=p.range,
        cardinality_subject=p.cardinality_subject,
        cardinality_object=p.cardinality_object,
        symmetric=p.symmetric, transitive=p.transitive,
        temporal=p.temporal, high_stakes=p.high_stakes,
        ui_hints={"proposed_by": actor_id or "agent"},
    )
    return {"relation": {"id": r.id, "slug": r.slug, "name": r.name}}


async def _propose_ontology(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ProposeOntologyIn) -> dict[str, Any]:
    samples = list(p.samples)
    if p.episode_ids:
        result = await session.execute(
            text("SELECT content_text FROM episode WHERE id = ANY(:ids)"),
            {"ids": p.episode_ids},
        )
        samples.extend(r[0] for r in result if r[0])
    if not samples:
        return {"error": "no samples provided"}

    proposal = await auto_ontology.propose_ontology(
        session, workspace_id=workspace_id, samples=samples
    )
    out: dict[str, Any] = {"proposal": proposal.model_dump()}
    if p.apply:
        applied = await auto_ontology.apply_proposal(
            session, workspace_id=workspace_id, proposal=proposal, actor_id=actor_id
        )
        out["applied"] = {
            "created_types": applied.created_types,
            "created_relations": applied.created_relations,
            "skipped_types": applied.skipped_types,
            "skipped_relations": applied.skipped_relations,
        }
    return out


async def _get_provenance(session: AsyncSession, workspace_id: str, actor_id: str | None, p: GetProvenanceIn, principal: Principal) -> dict[str, Any]:
    doc = await prov_mod.get_edge_provenance(session, p.fact_id, principal=principal)
    if not doc:
        return {"error": "fact not found"}
    return doc


async def _get_fact(
    session: AsyncSession,
    workspace_id: str,
    actor_id: str | None,
    p: GetFactIn,
    principal: Principal,
) -> dict[str, Any]:
    """Decision-support shortcut for functional agents.

    Returns ONE structured fact (subject + predicate) with confidence,
    freshness, label slugs, and provenance attached. Replaces the
    "search → filter → get_provenance" loop with a single call.
    """
    subject = await entity_mod.get(session, p.subject)
    if not subject:
        return {"error": "subject_not_found", "subject": p.subject}

    relation = await ontology_mod.get_relation_type(session, p.predicate)
    if not relation:
        return {"error": "predicate_not_found", "predicate": p.predicate}

    if p.as_of is not None:
        rows = await edge_mod.as_of(
            session,
            valid_at=p.as_of,
            subject_id=subject.id,
            predicate=p.predicate,
            principal=principal,
        )
    else:
        rows = await edge_mod.live_edges(
            session,
            subject_id=subject.id,
            predicate=p.predicate,
            principal=principal,
        )

    if p.object is not None:
        obj = await entity_mod.get(session, p.object)
        if obj is None:
            return {"error": "object_not_found", "object": p.object}
        rows = [r for r in rows if r.object_id == obj.id]

    if not rows:
        return {"error": "no_fact"}

    # When multiple live values exist (e.g. cardinality-many) and the
    # caller didn't disambiguate via object=, return the list with a
    # ``multiple`` flag so the agent can choose.
    if len(rows) > 1 and p.object is None:
        return {
            "multiple": True,
            "candidates": [
                await _shape_fact(session, edge, principal=principal)
                for edge in rows
            ],
        }

    edge = rows[0]
    if (
        p.require_min_confidence is not None
        and (edge.confidence is None
             or edge.confidence < p.require_min_confidence)
    ):
        return {
            "error": "below_min_confidence",
            "confidence": edge.confidence,
            "required": p.require_min_confidence,
        }
    return await _shape_fact(session, edge, principal=principal)


async def _shape_fact(
    session: AsyncSession,
    edge: edge_mod.Edge,
    *,
    principal: Principal | None = None,
) -> dict[str, Any]:
    """Canonical agent-facing fact shape used by ``get_fact`` (and the
    ``multiple`` candidate list)."""
    subject = await entity_mod.get(session, edge.subject_id)
    obj = await entity_mod.get(session, edge.object_id)
    label_rows = await sens_mod.labels_for(
        session, target_kind="edge", target_id=edge.id
    )
    label_slugs = [row.slug for row in label_rows]
    provenance = await prov_mod.get_edge_provenance(
        session, edge.id, principal=principal
    )
    # Freshness in days from now; for an open-ended edge use the
    # ``valid_from`` lower bound.
    try:
        from datetime import datetime as _dt
        vf = _dt.fromisoformat(edge.valid_from.replace(" ", "T"))
        if vf.tzinfo is None:
            vf = vf.replace(tzinfo=UTC)
        freshness_days = max(
            0, int((_dt.now(UTC) - vf).total_seconds() // 86400)
        )
    except Exception:
        freshness_days = None
    return {
        "edge_id": edge.id,
        "subject": (
            {"id": subject.id, "canonical": subject.canonical}
            if subject else {"id": edge.subject_id}
        ),
        "predicate": edge.predicate_slug,
        "object": (
            {"id": obj.id, "canonical": obj.canonical}
            if obj else {"id": edge.object_id}
        ),
        "fact": edge.fact,
        "confidence": edge.confidence,
        "freshness_days": freshness_days,
        "valid_from": edge.valid_from,
        "valid_to": edge.valid_to,
        "label_slugs": label_slugs,
        "wasGeneratedBy": (
            provenance.get("wasGeneratedBy") if provenance else None
        ),
        "wasDerivedFrom": (
            provenance.get("wasDerivedFrom") if provenance else None
        ),
    }


async def _list_proposals(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ListProposalsIn) -> dict[str, Any]:
    rows = await proposals_mod.list_proposals(
        session,
        workspace_id=workspace_id,
        status=p.status,
        limit=p.limit,
        offset=p.offset,
        predicate_id=p.predicate_id,
        source_kind=p.source_kind,
    )
    return {"proposals": [asdict(r) for r in rows]}


async def _approve_proposal(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ApproveProposalIn) -> dict[str, Any]:
    try:
        edge = await proposals_mod.approve_proposal(
            session,
            proposal_id=p.proposal_id,
            principal_user_id=actor_id,
            comment=p.comment,
        )
    except proposals_mod.ProposalError as exc:
        return {"error": str(exc)}
    return {"approved_edge_id": edge.id, "edge": asdict(edge)}


async def _list_labels(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ListLabelsIn) -> dict[str, Any]:
    labels = await sens_mod.list_labels(session, workspace_id=workspace_id)
    return {"labels": [asdict(label) for label in labels]}


async def _list_action_types(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ListActionTypesIn) -> dict[str, Any]:
    types = await action_mod.list_action_types(session, workspace_id=workspace_id)
    return {"action_types": [asdict(t) for t in types]}


async def _execute_action(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ExecuteActionIn, principal: Principal) -> dict[str, Any]:
    from uuid import uuid4 as _uuid4
    try:
        inv = await action_mod.execute_action(
            session,
            workspace_id=workspace_id,
            type_slug=p.type_slug,
            input=p.input,
            idempotency_key=p.idempotency_key or str(_uuid4()),
            principal=principal,
        )
    except action_mod.ActionError as exc:
        return {"error": str(exc)}
    return {"invocation": asdict(inv)}


async def _list_action_invocations(session: AsyncSession, workspace_id: str, actor_id: str | None, p: ListActionInvocationsIn) -> dict[str, Any]:
    rows = await action_mod.list_invocations(
        session,
        workspace_id=workspace_id,
        status=p.status,
        limit=p.limit,
        offset=p.offset,
    )
    return {"invocations": [asdict(r) for r in rows]}


async def _assign_label(session: AsyncSession, workspace_id: str, actor_id: str | None, p: AssignLabelIn) -> dict[str, Any]:
    try:
        await sens_mod.assign_label(
            session,
            workspace_id=workspace_id,
            target_kind=p.target_kind,
            target_id=p.target_id,
            label_slug=p.label_slug,
            assigned_by=actor_id,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


async def _reject_proposal(session: AsyncSession, workspace_id: str, actor_id: str | None, p: RejectProposalIn) -> dict[str, Any]:
    try:
        rejected = await proposals_mod.reject_proposal(
            session,
            proposal_id=p.proposal_id,
            principal_user_id=actor_id,
            reason=p.reason,
        )
    except proposals_mod.ProposalError as exc:
        return {"error": str(exc)}
    return asdict(rejected)


async def _as_of_query(session: AsyncSession, workspace_id: str, actor_id: str | None, p: AsOfIn, principal: Principal) -> dict[str, Any]:
    subject_id: str | None = None
    if p.subject:
        resolved = await entity_mod.get(session, p.subject)
        if resolved:
            subject_id = resolved.id
    edges = await edge_mod.as_of(
        session, valid_at=p.valid_at, subject_id=subject_id, predicate=p.predicate,
        principal=principal,
    )
    return {"edges": [asdict(e) for e in edges]}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ToolHandler = Callable[[AsyncSession, str, str | None, BaseModel], Any]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: type[BaseModel]
    handler: Any  # Callable

    model_config = {"arbitrary_types_allowed": True}


TOOLS: list[ToolSpec] = [
    ToolSpec(name="search_memory", description="Hybrid search (vector + FTS + trigram + RRF) across entities, edges, episodes, and blocks. Supports filtering by entity type and as-of valid time.", input_schema=SearchMemoryIn, handler=_search_memory),
    ToolSpec(name="get_entity", description="Fetch an entity by id, IRI, or canonical name, with optional live edges, full history, and document backlinks.", input_schema=GetEntityIn, handler=_get_entity),
    ToolSpec(name="graph_query", description="Bounded n-hop traversal of the typed property graph from one or more seed entities, with predicate/type filters and optional as-of valid time.", input_schema=GraphQueryIn, handler=_graph_query),
    ToolSpec(name="add_fact", description="Insert a new edge (relationship) between two entities. Runs the contradictor for high-stakes predicates and closes any overlapping live fact.", input_schema=AddFactIn, handler=_add_fact),
    ToolSpec(name="invalidate_fact", description="Close an edge's valid_time and sys_time windows. Records the reason in the audit log.", input_schema=InvalidateFactIn, handler=_invalidate_fact),
    ToolSpec(name="add_episode", description="Record a raw episode (message, document, observation) and schedule an extraction job.", input_schema=AddEpisodeIn, handler=_add_episode),
    ToolSpec(name="update_entity", description="Update an entity's canonical name, aliases, summary, or props. Validates props against the type's JSON Schema.", input_schema=UpdateEntityIn, handler=_update_entity),
    ToolSpec(name="ontology_describe", description="Return the current ontology: entity types (with hierarchy + optional schemas) and relation types (with domain/range/constraints).", input_schema=OntologyDescribeIn, handler=_ontology_describe),
    ToolSpec(name="create_entity_type", description="Create a new entity type in the ontology with an optional parent type and a list of JSON-Schema-ready properties.", input_schema=CreateEntityTypeIn, handler=_create_entity_type),
    ToolSpec(name="create_relation_type", description="Create a new relation type with domain/range constraints, cardinality, and temporal / symmetric / transitive / high-stakes flags.", input_schema=CreateRelationTypeIn, handler=_create_relation_type),
    ToolSpec(name="propose_ontology", description="Ask the LLM to propose an ontology (entity and relation types) from sample text or existing episodes. Optionally apply the proposal immediately.", input_schema=ProposeOntologyIn, handler=_propose_ontology),
    ToolSpec(name="as_of_query", description="Query edges as they were at a past valid time (bi-temporal as-of query).", input_schema=AsOfIn, handler=_as_of_query),
    ToolSpec(name="get_provenance", description="Return W3C PROV-O JSON-LD for a fact (edge), including the activity that produced it, the agent (LLM / user / system), and the source episode it was derived from.", input_schema=GetProvenanceIn, handler=_get_provenance),
    ToolSpec(name="get_fact", description="Decision-support shortcut: return one structured fact for (subject, predicate) with confidence, freshness, label slugs, and provenance attached. Returns {error: 'no_fact'} when no live edge exists, or {multiple: true, candidates: [...]} when the subject has several values and ``object`` was not provided.", input_schema=GetFactIn, handler=_get_fact),
    ToolSpec(name="list_proposals", description="List facts in the review queue (pending / approved / rejected / superseded). Use this to surface low-confidence extractions that need human approval.", input_schema=ListProposalsIn, handler=_list_proposals),
    ToolSpec(name="approve_proposal", description="Approve a pending fact and promote it to a live edge. Reuses the same cardinality / contradictor invariants as direct fact insertion.", input_schema=ApproveProposalIn, handler=_approve_proposal),
    ToolSpec(name="reject_proposal", description="Reject a pending fact with a written reason. The proposal stays as audit evidence; no edge is created.", input_schema=RejectProposalIn, handler=_reject_proposal),
    ToolSpec(name="list_labels", description="List all sensitivity labels in the workspace, with their hierarchical paths and metadata. Use to discover label slugs before assigning.", input_schema=ListLabelsIn, handler=_list_labels),
    ToolSpec(name="assign_label", description="Assign a sensitivity label to an edge or episode. The label and target must already exist; label policies are re-evaluated at retrieval time.", input_schema=AssignLabelIn, handler=_assign_label),
    ToolSpec(name="list_action_types", description="List the registered kinetic action types in the workspace (catalog). Returns input_schema, required_role, idempotency requirements, and declared side_effects.", input_schema=ListActionTypesIn, handler=_list_action_types),
    ToolSpec(name="execute_action", description="Invoke a registered action by slug. Idempotent on (type_slug, idempotency_key): re-invocation returns the cached result. Validates input against the action's JSON Schema.", input_schema=ExecuteActionIn, handler=_execute_action),
    ToolSpec(name="list_action_invocations", description="List action invocations in this workspace, optionally filtered by status (pending/approved/executing/completed/failed/rejected).", input_schema=ListActionInvocationsIn, handler=_list_action_invocations),
]


TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


async def invoke_tool(
    session: AsyncSession,
    *,
    workspace_id: str,
    actor_id: str | None,
    name: str,
    arguments: dict[str, Any],
    session_id: str | None = None,
    principal: Principal | None = None,
) -> dict[str, Any]:
    spec = TOOLS_BY_NAME.get(name)
    if not spec:
        return {"error": f"unknown tool: {name}"}

    t0 = time.monotonic()
    err: str | None = None
    parsed: BaseModel | None = None
    result: dict[str, Any] = {}
    try:
        parsed = spec.input_schema.model_validate(arguments)
        # Tools that opted into the per-source ACL filter accept `principal`
        # as a fifth positional argument. Older handlers don't take it; we
        # detect that via parameter introspection rather than a registry
        # flag so the call sites stay terse.
        import inspect as _inspect
        sig = _inspect.signature(spec.handler)
        if "principal" in sig.parameters:
            result = await spec.handler(session, workspace_id, actor_id, parsed, principal)
        else:
            result = await spec.handler(session, workspace_id, actor_id, parsed)
    except Exception as exc:  # log and return structured error
        err = str(exc)
        log.warning("mcp.tool.failed", tool=name, error=err)
        result = {"error": err}

    latency_ms = int((time.monotonic() - t0) * 1000)

    await session.execute(
        text(
            """
            INSERT INTO agent_tool_call
              (workspace_id, session_id, tool, input, output, error, latency_ms)
            VALUES
              (:workspace_id, :session_id, :tool,
               CAST(:input AS jsonb), CAST(:output AS jsonb), :error, :latency)
            """
        ),
        {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "tool": name,
            "input": _json(arguments),
            "output": _json(result),
            "error": err,
            "latency": latency_ms,
        },
    )

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug_by_id(snap: ontology_mod.OntologySnapshot, type_id: str | None) -> str | None:
    if not type_id:
        return None
    t = snap.type_by_id(type_id)
    return t.slug if t else None


def _props_to_schema(properties: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in properties:
        name = p.get("name")
        if not name:
            continue
        ptype = p.get("type", "string")
        label = p.get("label", name.replace("_", " ").title())
        if ptype == "enum":
            props[name] = {"type": "string", "enum": p.get("enum_values") or [], "title": label}
        elif ptype == "date":
            props[name] = {"type": "string", "format": "date", "title": label}
        elif ptype == "date-time":
            props[name] = {"type": "string", "format": "date-time", "title": label}
        else:
            props[name] = {"type": ptype, "title": label}
        if p.get("required"):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": True}
    if required:
        schema["required"] = required
    return schema


def _json(v: Any) -> str:
    import json
    return json.dumps(v, default=str)
