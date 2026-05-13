"""Bi-temporal edge service.

Edges are the relationships of the knowledge graph. Every edge carries
two time axes:

- ``valid_time``  : when the relationship is true in the real world
- ``sys_time``    : when the system believes it

Edges are never hard-deleted. They are closed by setting ``sys_time``'s
upper bound to ``now()`` ("invalidate") or by setting ``valid_time``'s
upper bound ("retire"). Reads pick the right axis:

- Current truth     : ``upper(sys_time) = 'infinity' AND valid_time @> now()``
- As-of system      : ``sys_time @> <sys_ts>``
- As-of valid       : ``valid_time @> <valid_ts>``
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.acl import edge_visibility_clause
from app.auth.jwt import Principal
from app.core.logging import get_logger
from app.domain import ontology as ontology_mod
from app.domain.ontology import OntologyError
from app.llm.embedding import get_embedding_client
from app.llm.vector_utils import to_pg_vector

log = get_logger(__name__)


class EdgeError(Exception):
    pass


@dataclass
class Edge:
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


INF = "infinity"


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

async def add_fact(
    session: AsyncSession,
    *,
    workspace_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    fact: str | None = None,
    props: dict[str, Any] | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    source_id: str | None = None,
    source_kind: str | None = None,
    confidence: float | None = None,
    created_by: str | None = None,
    embed: bool = True,
    run_contradictor: bool = True,
    prov_activity_id: str | None = None,
) -> Edge:
    """Insert a new edge, running the contradictor when required.

    Returns the newly inserted edge. If the contradictor closed a prior
    edge, that closure is recorded in ``audit_log``.
    """
    relation = await ontology_mod.get_relation_type(session, predicate)
    if not relation:
        raise OntologyError(f"relation type not found: {predicate}")

    # Subject / object type fetch for domain/range validation.
    sub_type, obj_type = await _subject_object_types(session, subject_id, object_id)
    if not sub_type or not obj_type:
        raise EdgeError("subject or object entity not found")

    await ontology_mod.validate_edge(
        session,
        relation=relation,
        subject_type_id=sub_type,
        object_type_id=obj_type,
    )

    if not fact:
        fact = await _derive_fact(session, subject_id, predicate, object_id)

    vt_from = valid_from or _utcnow()
    vt_to = valid_to  # None → open (infinity)

    fact_embedding: list[float] | None = None
    if embed:
        try:
            fact_embedding = await get_embedding_client().embed_one(fact)
        except Exception:
            fact_embedding = None

    if run_contradictor and relation.high_stakes:
        from app.llm.contradictor import run as run_contradictor_fn

        await run_contradictor_fn(
            session,
            workspace_id=workspace_id,
            subject_id=subject_id,
            relation=relation,
            new_fact=fact,
            new_fact_embedding=fact_embedding,
            new_valid_from=vt_from,
            actor_id=created_by,
        )

    # Pre-generate the new edge id so we can link `invalidated_by` on any
    # overlapping live edges that cardinality_object=one forces us to close.
    # Insert FIRST so the FK constraint on `invalidated_by` is satisfied when
    # we then UPDATE the older overlapping edges.
    edge_id = str(uuid4())

    await session.execute(
        text(
            """
            INSERT INTO edge (
              id, workspace_id, subject_id, predicate_id, object_id,
              fact, fact_embedding, props,
              valid_time, sys_time,
              source_id, source_kind, confidence, created_by, prov_activity_id
            ) VALUES (
              :id, :workspace_id, :subject_id, :predicate_id, :object_id,
              :fact, CAST(:fact_embedding AS vector), CAST(:props AS jsonb),
              tstzrange(:vt_from, COALESCE(:vt_to, 'infinity'::timestamptz), '[)'),
              tstzrange(clock_timestamp(), 'infinity'::timestamptz, '[)'),
              :source_id, :source_kind, :confidence, :created_by, :prov_activity_id
            )
            """
        ),
        {
            "id": edge_id,
            "workspace_id": workspace_id,
            "subject_id": subject_id,
            "predicate_id": relation.id,
            "object_id": object_id,
            "fact": fact,
            "fact_embedding": to_pg_vector(fact_embedding),
            "props": json.dumps(props or {}),
            "vt_from": vt_from,
            "vt_to": vt_to,
            "source_id": source_id,
            "source_kind": source_kind,
            "confidence": confidence,
            "created_by": created_by,
            "prov_activity_id": prov_activity_id,
        },
    )

    if relation.cardinality_object == "one" and not relation.symmetric:
        await session.execute(
            text(
                """
                UPDATE edge
                SET sys_time = tstzrange(lower(sys_time), clock_timestamp(), '[)'),
                    invalidated_by = :new_edge_id
                WHERE workspace_id = :workspace_id
                  AND subject_id = :subject_id
                  AND predicate_id = :predicate_id
                  AND id <> :new_edge_id
                  AND upper(sys_time) = 'infinity'
                  AND valid_time && tstzrange(:vt_from, COALESCE(:vt_to, 'infinity'::timestamptz), '[)')
                """
            ),
            {
                "new_edge_id": edge_id,
                "workspace_id": workspace_id,
                "subject_id": subject_id,
                "predicate_id": relation.id,
                "vt_from": vt_from,
                "vt_to": vt_to,
            },
        )

    edge = await get(session, edge_id)
    assert edge is not None
    return edge


async def propose_fact(
    session: AsyncSession,
    *,
    workspace_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    fact: str | None = None,
    props: dict[str, Any] | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    source_id: str | None = None,
    source_kind: str | None = None,
    confidence: float,
    created_by: str | None = None,
    prov_activity_id: str | None = None,
) -> FactWriteResult:
    """Threshold-aware fact write.

    Used by the extraction pipeline (and any other automated producer)
    instead of :func:`add_fact`. Consults ``extraction_policy`` and routes
    the fact to ``edge`` directly, to ``pending_fact(status='pending')``
    for human review, or to ``pending_fact(status='rejected')`` if
    confidence is below the workspace's auto-reject floor.
    """
    # Lazy import to avoid module-level circularity with proposals.
    from app.domain import proposals as proposals_mod

    relation = await ontology_mod.get_relation_type(session, predicate)
    if not relation:
        raise OntologyError(f"relation type not found: {predicate}")

    sub_type, obj_type = await _subject_object_types(session, subject_id, object_id)
    if not sub_type or not obj_type:
        raise EdgeError("subject or object entity not found")

    await ontology_mod.validate_edge(
        session,
        relation=relation,
        subject_type_id=sub_type,
        object_type_id=obj_type,
    )

    if not fact:
        fact = await _derive_fact(session, subject_id, predicate, object_id)

    thresholds = await proposals_mod.get_thresholds(
        session,
        workspace_id=workspace_id,
        # Threshold per (subject) entity-type allowed; relation takes precedence.
        entity_type_id=sub_type,
        relation_type_id=relation.id,
    )

    # High-stakes contradiction guard: if this fact would close an existing
    # live edge under cardinality-one, queue it for review regardless of
    # confidence. Approval re-runs add_fact (which closes the old edge via
    # the contradictor) under explicit human authorization.
    if (
        relation.high_stakes
        and relation.cardinality_object == "one"
        and not relation.symmetric
    ):
        # ``clock_timestamp()`` rather than ``now()`` because both
        # statements may run inside the same transaction — ``now()``
        # returns the transaction start time, which is before the
        # existing edge's ``valid_from`` and would miss the conflict.
        conflict = await session.execute(
            text(
                """
                SELECT id::text FROM edge
                WHERE workspace_id = :ws
                  AND subject_id = :s
                  AND predicate_id = :p
                  AND object_id <> :o
                  AND upper(sys_time) = 'infinity'
                  AND valid_time @> clock_timestamp()
                LIMIT 1
                """
            ),
            {"ws": workspace_id, "s": subject_id, "p": relation.id, "o": object_id},
        )
        if conflict.first() is not None:
            pending_id = await proposals_mod.enqueue_pending_fact(
                session,
                workspace_id=workspace_id,
                subject_id=subject_id,
                predicate_id=relation.id,
                object_id=object_id,
                fact=fact,
                props=props,
                valid_from=valid_from,
                valid_to=valid_to,
                source_id=source_id,
                source_kind=source_kind,
                confidence=confidence,
                prov_activity_id=prov_activity_id,
                status="pending",
                reason="high_stakes_contradiction",
            )
            return FactWriteResult(kind="pending", pending_fact_id=pending_id)

    # Below the floor — record as auto-rejected for audit, no edge.
    if confidence < thresholds.auto_reject_below:
        pending_id = await proposals_mod.enqueue_pending_fact(
            session,
            workspace_id=workspace_id,
            subject_id=subject_id,
            predicate_id=relation.id,
            object_id=object_id,
            fact=fact,
            props=props,
            valid_from=valid_from,
            valid_to=valid_to,
            source_id=source_id,
            source_kind=source_kind,
            confidence=confidence,
            prov_activity_id=prov_activity_id,
            status="rejected",
            reason="auto_rejected_below_floor",
        )
        return FactWriteResult(kind="rejected", pending_fact_id=pending_id)

    # In the review band — enqueue, don't insert.
    if confidence < thresholds.min_confidence:
        pending_id = await proposals_mod.enqueue_pending_fact(
            session,
            workspace_id=workspace_id,
            subject_id=subject_id,
            predicate_id=relation.id,
            object_id=object_id,
            fact=fact,
            props=props,
            valid_from=valid_from,
            valid_to=valid_to,
            source_id=source_id,
            source_kind=source_kind,
            confidence=confidence,
            prov_activity_id=prov_activity_id,
            status="pending",
            reason="below_threshold",
        )
        return FactWriteResult(kind="pending", pending_fact_id=pending_id)

    # At or above threshold — write through to edge.
    edge = await add_fact(
        session,
        workspace_id=workspace_id,
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        fact=fact,
        props=props,
        valid_from=valid_from,
        valid_to=valid_to,
        source_id=source_id,
        source_kind=source_kind,
        confidence=confidence,
        created_by=created_by,
        prov_activity_id=prov_activity_id,
    )
    return FactWriteResult(kind="edge", edge=edge)


@dataclass
class FactWriteResult:
    kind: str  # 'edge' | 'pending' | 'rejected'
    edge: Edge | None = None
    pending_fact_id: str | None = None


async def invalidate(
    session: AsyncSession,
    *,
    edge_id: str,
    invalidated_at: datetime | None = None,
    reason: str | None = None,
    actor_kind: str = "user",
    actor_id: str | None = None,
) -> Edge:
    """Close an edge in both axes.

    - ``sys_time`` is closed at ``now()`` (our belief changed now).
    - ``valid_time`` is closed at ``invalidated_at`` (the relation stopped
      being true at that world time). If None, uses ``now()``.
    """
    existing = await get(session, edge_id)
    if not existing:
        raise EdgeError("edge not found")

    invalid_at = invalidated_at or _utcnow()

    await session.execute(
        text(
            """
            UPDATE edge
            SET sys_time = tstzrange(lower(sys_time), clock_timestamp(), '[)'),
                valid_time = tstzrange(lower(valid_time), :invalid_at, '[)')
            WHERE id = :edge_id AND upper(sys_time) = 'infinity'
            """
        ),
        {"edge_id": edge_id, "invalid_at": invalid_at},
    )

    await session.execute(
        text(
            """
            INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                   target_kind, target_id, diff)
            VALUES (:workspace_id, :actor_kind, :actor_id, 'edge.invalidate',
                    'edge', :edge_id,
                    jsonb_build_object('reason', CAST(:reason AS text), 'invalidated_at', CAST(:invalid_at AS text)))
            """
        ),
        {
            "workspace_id": existing.workspace_id,
            "actor_kind": actor_kind,
            "actor_id": actor_id,
            "edge_id": edge_id,
            "reason": reason,
            "invalid_at": invalid_at.isoformat(),
        },
    )

    updated = await get(session, edge_id)
    assert updated is not None
    return updated


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _apply_acl(
    conditions: list[str],
    params: dict[str, Any],
    principal: Principal | None,
) -> None:
    """In-place: AND the per-source visibility clause into the WHERE.

    Pass ``principal=None`` to skip ACL filtering (legacy callers,
    background jobs, internal pipeline reads). Service-kind and
    admin/owner principals also short-circuit to TRUE inside
    ``edge_visibility_clause``.
    """
    if principal is None:
        return
    clause = edge_visibility_clause(principal, edge_alias="e")
    conditions.append(clause.text)
    for key, value in clause._bindparams.items():
        params[key] = value.value


async def get(
    session: AsyncSession, edge_id: str, *, principal: Principal | None = None
) -> Edge | None:
    conditions = ["e.id = :id"]
    params: dict[str, Any] = {"id": edge_id}
    _apply_acl(conditions, params, principal)
    result = await session.execute(
        text(_EDGE_SELECT + f" WHERE {' AND '.join(conditions)}"),
        params,
    )
    row = result.mappings().first()
    return _row_to_edge(row) if row else None


async def live_edges(
    session: AsyncSession,
    *,
    subject_id: str | None = None,
    object_id: str | None = None,
    predicate: str | None = None,
    at: datetime | None = None,
    limit: int = 100,
    principal: Principal | None = None,
) -> list[Edge]:
    """Return current-truth edges, optionally filtered."""
    conditions: list[str] = ["upper(e.sys_time) = 'infinity'"]
    params: dict[str, Any] = {"limit": limit}

    if at is None:
        conditions.append("e.valid_time @> now()")
    else:
        conditions.append("e.valid_time @> CAST(:at AS timestamptz)")
        params["at"] = at

    if subject_id:
        conditions.append("e.subject_id = :subject_id")
        params["subject_id"] = subject_id
    if object_id:
        conditions.append("e.object_id = :object_id")
        params["object_id"] = object_id
    if predicate:
        relation = await ontology_mod.get_relation_type(session, predicate)
        if not relation:
            return []
        conditions.append("e.predicate_id = :predicate_id")
        params["predicate_id"] = relation.id

    _apply_acl(conditions, params, principal)

    sql = _EDGE_SELECT + f" WHERE {' AND '.join(conditions)} ORDER BY lower(e.valid_time) DESC LIMIT :limit"
    result = await session.execute(text(sql), params)
    return [_row_to_edge(r) for r in result.mappings()]


async def history(
    session: AsyncSession,
    *,
    subject_id: str | None = None,
    object_id: str | None = None,
    predicate: str | None = None,
    limit: int = 200,
    principal: Principal | None = None,
) -> list[Edge]:
    """All edge rows ever recorded, including closed ones. Useful for timeline UI."""
    conditions: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if subject_id:
        conditions.append("e.subject_id = :subject_id"); params["subject_id"] = subject_id
    if object_id:
        conditions.append("e.object_id = :object_id"); params["object_id"] = object_id
    if predicate:
        relation = await ontology_mod.get_relation_type(session, predicate)
        if not relation: return []
        conditions.append("e.predicate_id = :predicate_id"); params["predicate_id"] = relation.id

    _apply_acl(conditions, params, principal)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = _EDGE_SELECT + f" {where} ORDER BY lower(e.sys_time) DESC, lower(e.valid_time) DESC LIMIT :limit"
    result = await session.execute(text(sql), params)
    return [_row_to_edge(r) for r in result.mappings()]


async def as_of(
    session: AsyncSession,
    *,
    valid_at: datetime,
    sys_at: datetime | None = None,
    subject_id: str | None = None,
    object_id: str | None = None,
    predicate: str | None = None,
    limit: int = 200,
    principal: Principal | None = None,
) -> list[Edge]:
    conditions: list[str] = []
    params: dict[str, Any] = {"limit": limit, "valid_at": valid_at}

    conditions.append("e.valid_time @> CAST(:valid_at AS timestamptz)")
    if sys_at:
        # Pinned to a past system-time: "what did we believe about that
        # valid time, as of that sys time".
        conditions.append("e.sys_time @> CAST(:sys_at AS timestamptz)")
        params["sys_at"] = sys_at
    # Otherwise: return the full bi-temporal view of the valid moment —
    # both the live edge (if any) AND the historical closed edge that was
    # true at that valid time. Callers can pass `sys_at=now()` for the
    # "current system view" variant.

    if subject_id:
        conditions.append("e.subject_id = :subject_id"); params["subject_id"] = subject_id
    if object_id:
        conditions.append("e.object_id = :object_id"); params["object_id"] = object_id
    if predicate:
        relation = await ontology_mod.get_relation_type(session, predicate)
        if not relation: return []
        conditions.append("e.predicate_id = :predicate_id"); params["predicate_id"] = relation.id

    _apply_acl(conditions, params, principal)

    sql = _EDGE_SELECT + f" WHERE {' AND '.join(conditions)} ORDER BY lower(e.valid_time) DESC LIMIT :limit"
    result = await session.execute(text(sql), params)
    return [_row_to_edge(r) for r in result.mappings()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EDGE_SELECT = """
SELECT
  e.id::text, e.workspace_id::text,
  e.subject_id::text, e.predicate_id::text, rt.slug AS predicate_slug,
  e.object_id::text,
  e.fact, e.props,
  lower(e.valid_time)::text AS valid_from,
  CASE WHEN upper(e.valid_time) = 'infinity' THEN NULL ELSE upper(e.valid_time)::text END AS valid_to,
  lower(e.sys_time)::text AS sys_from,
  CASE WHEN upper(e.sys_time) = 'infinity' THEN NULL ELSE upper(e.sys_time)::text END AS sys_to,
  e.source_id::text, e.source_kind, e.confidence,
  e.invalidated_by::text, e.created_by::text,
  e.created_at::text
FROM edge e
LEFT JOIN relation_type rt ON rt.id = e.predicate_id
"""


def _row_to_edge(row: Any) -> Edge:
    return Edge(
        id=row["id"],
        workspace_id=row["workspace_id"],
        subject_id=row["subject_id"],
        predicate_id=row["predicate_id"],
        predicate_slug=row.get("predicate_slug"),
        object_id=row["object_id"],
        fact=row["fact"],
        props=row["props"] or {},
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        sys_from=row["sys_from"],
        sys_to=row["sys_to"],
        source_id=row.get("source_id"),
        source_kind=row.get("source_kind"),
        confidence=row.get("confidence"),
        invalidated_by=row.get("invalidated_by"),
        created_by=row.get("created_by"),
        created_at=row["created_at"],
    )


async def _subject_object_types(
    session: AsyncSession, subject_id: str, object_id: str
) -> tuple[str | None, str | None]:
    result = await session.execute(
        text(
            """
            SELECT id::text AS id, type_id::text AS type_id
            FROM entity WHERE id = ANY(:ids) AND deleted_at IS NULL
            """
        ),
        {"ids": [subject_id, object_id]},
    )
    type_by_id: dict[str, str] = {row["id"]: row["type_id"] for row in result.mappings()}
    return type_by_id.get(subject_id), type_by_id.get(object_id)


async def _derive_fact(session: AsyncSession, subject_id: str, predicate: str, object_id: str) -> str:
    result = await session.execute(
        text(
            """
            SELECT s.canonical AS s, rt.name AS p, o.canonical AS o
            FROM entity s, entity o, relation_type rt
            WHERE s.id = :s AND o.id = :o
              AND (rt.id::text = :p OR rt.slug = :p)
            """
        ),
        {"s": subject_id, "o": object_id, "p": predicate},
    )
    row = result.mappings().first()
    if row:
        return f"{row['s']} {row['p']} {row['o']}"
    return f"{subject_id} {predicate} {object_id}"


def _utcnow() -> datetime:
    return datetime.now(UTC)
