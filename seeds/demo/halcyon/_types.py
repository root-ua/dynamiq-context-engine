"""Shared dataclasses for the Halcyon demo dataset.

These are pure data containers. Nothing here touches a database; the
seeder in `backend/app/domain/demo_seeder.py` consumes them.

Keys (`key: str`) are stable, author-defined identifiers. The seeder
uses them as a dedupe handle: re-running the seeder with the same keys
updates the existing rows rather than creating duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class EntitySeed:
    """A person / organization / project etc."""

    key: str  # stable ID for intra-dataset refs, not stored
    type_slug: str  # ontology slug: "person" | "organization" | "project" | ...
    canonical: str  # display name
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSeed:
    """A typed, bi-temporal edge between two entities."""

    subject_key: str
    predicate: str  # relation slug
    object_key: str
    fact: str | None = None  # natural-language claim; falls back to predicate
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float | None = None  # None == 1.0 (fully asserted)
    source_kind: str | None = None  # "document" | "episode" | "agent" | "manual"
    source_ref_key: str | None = None  # key into DOCUMENTS or EPISODES

    # If set, invalidate this edge's valid_time at the given timestamp
    # *after* inserting it. Models "we used to believe X, then learned Y."
    invalidate_at: datetime | None = None
    invalidate_reason: str | None = None


@dataclass(frozen=True)
class DocumentSeed:
    """A BlockNote document authored by someone in the workspace."""

    key: str
    title: str
    type_slug: str  # "document" | "note"
    author_key: str | None = None  # person key
    occurred_at: datetime | None = None  # document creation/as-of time
    # BlockNote-style block list. Each block is a dict with:
    #   {"id": uuid-like-string, "type": "paragraph|heading|bulletListItem|...",
    #    "content": [inline nodes],
    #    "props": {...}}
    # Inline entity mentions have shape:
    #   {"type": "entityMention", "props": {"entityId": "<key>"}}
    # The seeder resolves those keys to actual entity UUIDs at insert time.
    blocks: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class EpisodeSeed:
    """Raw ingested content + the entity refs the extractor would produce."""

    key: str
    source_kind: str  # "meeting_transcript" | "slack_export" | "email" | ...
    source_ref: str | None
    occurred_at: datetime
    content_text: str
    # Entities the extractor "found" in this episode. Referenced by entity
    # key. The seeder writes these to a synthetic extraction row so the
    # Extraction Results pane has real data to display.
    extracted_entity_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentToolCallSeed:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    latency_ms: int
    occurred_at: datetime
    error: str | None = None


@dataclass(frozen=True)
class AgentSessionSeed:
    """A realistic MCP agent session with a handful of tool calls."""

    key: str
    client: str  # "claude-code" | "cursor" | "claude-desktop"
    started_at: datetime
    calls: tuple[AgentToolCallSeed, ...]


@dataclass(frozen=True)
class EntityTypeSeed:
    """Workspace-scoped entity type addition (extends a built-in type)."""

    slug: str
    name: str
    extends: str
    description: str
    schema: dict[str, Any]
    ui_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationTypeSeed:
    """Workspace-scoped relation type addition."""

    slug: str
    name: str
    description: str
    domain: str
    range_: str
    cardinality_subject: str = "many"  # "one" | "many"
    cardinality_object: str = "many"
    temporal: bool = True
