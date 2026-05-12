"""Shared Pydantic request/response models for the REST API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------

class EntityTypeOut(BaseModel):
    id: str
    workspace_id: str | None
    name: str
    slug: str
    extends_id: str | None
    hierarchy: str
    json_schema: dict[str, Any] = Field(..., alias="schema")
    ui_hints: dict[str, Any]
    description: str | None
    system: bool

    model_config = ConfigDict(populate_by_name=True)


class EntityTypeCreate(BaseModel):
    name: str
    slug: str | None = None
    extends: str | None = None
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    ui_hints: dict[str, Any] | None = None
    description: str | None = None
    system: bool = False

    model_config = ConfigDict(populate_by_name=True)


class EntityTypeUpdate(BaseModel):
    name: str | None = None
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    ui_hints: dict[str, Any] | None = None
    description: str | None = None
    extends: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class RelationTypeOut(BaseModel):
    id: str
    workspace_id: str | None
    name: str
    slug: str
    description: str | None
    domain_type_id: str | None
    range_type_id: str | None
    cardinality_subject: Literal["one", "many"]
    cardinality_object: Literal["one", "many"]
    inverse_of_id: str | None
    symmetric: bool
    transitive: bool
    temporal: bool
    high_stakes: bool
    ui_hints: dict[str, Any]
    system: bool


class RelationTypeCreate(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None
    domain: str | None = None
    range: str | None = None
    cardinality_subject: Literal["one", "many"] = "many"
    cardinality_object: Literal["one", "many"] = "many"
    inverse_of: str | None = None
    symmetric: bool = False
    transitive: bool = False
    temporal: bool = True
    high_stakes: bool = False
    ui_hints: dict[str, Any] | None = None
    system: bool = False


class RelationTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cardinality_subject: Literal["one", "many"] | None = None
    cardinality_object: Literal["one", "many"] | None = None
    domain: str | None = None
    range: str | None = None
    symmetric: bool | None = None
    transitive: bool | None = None
    temporal: bool | None = None
    high_stakes: bool | None = None
    ui_hints: dict[str, Any] | None = None


class OntologySnapshotOut(BaseModel):
    types: list[EntityTypeOut]
    relations: list[RelationTypeOut]


class OntologyProposeIn(BaseModel):
    samples: list[str] | None = None
    episode_ids: list[str] | None = None
    apply: bool = False


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

class EntityOut(BaseModel):
    id: str
    workspace_id: str
    type_id: str
    type_slug: str | None
    iri: str
    canonical: str
    aliases: list[str]
    summary: str | None
    props: dict[str, Any]
    merged_into_id: str | None
    created_by: str | None
    created_at: str
    updated_at: str


class EntityCreate(BaseModel):
    type: str = Field(..., description="Entity type slug or UUID")
    canonical: str
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class EntityUpdate(BaseModel):
    canonical: str | None = None
    aliases: list[str] | None = None
    summary: str | None = None
    props: dict[str, Any] | None = None


class EntityMergeIn(BaseModel):
    loser_id: str


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

class EdgeOut(BaseModel):
    id: str
    workspace_id: str
    subject_id: str
    predicate_id: str
    predicate_slug: str | None
    object_id: str
    fact: str
    props: dict[str, Any]
    valid_from: str
    valid_to: str | None
    sys_from: str
    sys_to: str | None
    source_id: str | None
    source_kind: str | None
    confidence: float | None
    invalidated_by: str | None
    created_by: str | None
    created_at: str


class EdgeCreate(BaseModel):
    subject_id: str
    predicate: str = Field(..., description="Relation type slug or UUID")
    object_id: str
    fact: str | None = None
    props: dict[str, Any] | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_id: str | None = None
    source_kind: str | None = None
    confidence: float | None = None


class EdgeInvalidate(BaseModel):
    invalidated_at: datetime | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    id: str
    workspace_id: str
    entity_id: str
    title: str
    type_slug: str
    updated_at: str


class DocumentCreate(BaseModel):
    title: str
    type: str = "note"
    props: dict[str, Any] | None = None


class BlockIn(BaseModel):
    id: str
    parent_block_id: str | None = None
    position: float = 0
    block_type: str = "paragraph"
    content: Any = None
    props: dict[str, Any] | None = None
    search_text: str | None = None


class BlockTreeIn(BaseModel):
    blocks: list[BlockIn]


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

class EpisodeOut(BaseModel):
    id: str
    workspace_id: str
    source_kind: str
    source_ref: str | None
    occurred_at: str
    ingested_at: str
    content_text: str | None
    processing_status: str
    processing_error: str | None


class EpisodeCreate(BaseModel):
    content: str | dict[str, Any]
    source_kind: str = "manual"
    source_ref: str | None = None
    occurred_at: datetime | None = None
    extract: bool = True


# ---------------------------------------------------------------------------
# Search / graph
# ---------------------------------------------------------------------------

class SearchIn(BaseModel):
    query: str
    limit: int = 20
    include_kinds: list[Literal["entity", "edge", "episode", "block"]] = Field(
        default_factory=lambda: ["entity", "edge", "episode", "block"]
    )
    entity_type: str | None = None
    as_of_valid: datetime | None = None
    graph_expand: bool = False


class SearchHit(BaseModel):
    kind: str
    id: str
    title: str
    snippet: str
    score: float
    payload: dict[str, Any]


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHit]


class GraphTraverseIn(BaseModel):
    seeds: list[str]
    max_hops: int = 2
    direction: Literal["out", "in", "both"] = "both"
    predicates: list[str] | None = None
    types: list[str] | None = None
    as_of_valid: datetime | None = None
    max_nodes: int = 500


class GraphNodeOut(BaseModel):
    id: str
    type: str
    canonical: str
    iri: str
    distance: int


class GraphEdgeOut(BaseModel):
    id: str
    subject_id: str
    object_id: str
    predicate: str
    fact: str
    valid_from: str
    valid_to: str | None


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

class WorkspaceOut(BaseModel):
    id: str
    slug: str
    name: str
    settings: dict[str, Any]
    created_at: str


class WorkspaceCreate(BaseModel):
    slug: str
    name: str
    ontology_mode: Literal["strict", "flexible", "auto"] = "flexible"


class WorkspaceSettingsUpdate(BaseModel):
    name: str | None = None
    ontology_mode: Literal["strict", "flexible", "auto"] | None = None
