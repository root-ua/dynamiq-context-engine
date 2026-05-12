"""MCP tool registry.

Each tool is a thin wrapper around a domain service call, with a
Pydantic input schema used both for JSON-RPC (MCP) and for REST
``/mcp/tools/{name}`` invocations.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import Principal
from app.core.logging import get_logger
from app.domain import auto_ontology
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain import ontology as ontology_mod
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


async def _add_fact(session: AsyncSession, workspace_id: str, actor_id: str | None, p: AddFactIn) -> dict[str, Any]:
    subject = await entity_mod.get(session, p.subject)
    obj = await entity_mod.get(session, p.object)
    if not subject or not obj:
        return {"error": "subject or object not found"}

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


async def _add_episode(session: AsyncSession, workspace_id: str, actor_id: str | None, p: AddEpisodeIn) -> dict[str, Any]:
    ep = await episode_mod.add_episode(
        session,
        workspace_id=workspace_id,
        content=p.content,
        source_kind=p.source_kind,
        source_ref=p.source_ref,
        occurred_at=p.occurred_at,
        created_by=actor_id,
    )
    if p.extract:
        await enqueue_extraction(
            workspace_id=workspace_id, episode_id=ep.id, actor_id=actor_id,
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
