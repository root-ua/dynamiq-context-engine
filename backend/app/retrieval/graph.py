"""Graph traversal over the typed property graph.

Uses Postgres recursive CTEs. Bounded by ``max_hops`` with a visited-set
guard to avoid cycles. Returns nodes + edges in the subgraph rooted at
``seeds`` that match the optional filters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.acl import edge_visibility_clause
from app.auth.jwt import Principal


@dataclass
class GraphNode:
    id: str
    type: str
    canonical: str
    iri: str
    distance: int


@dataclass
class GraphEdge:
    id: str
    subject_id: str
    object_id: str
    predicate: str
    fact: str
    valid_from: str
    valid_to: str | None


@dataclass
class Subgraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


async def traverse(
    session: AsyncSession,
    *,
    workspace_id: str,
    seeds: list[str],
    max_hops: int = 2,
    direction: Literal["out", "in", "both"] = "both",
    predicate_slugs: list[str] | None = None,
    type_slugs: list[str] | None = None,
    as_of_valid: str | None = None,
    max_nodes: int = 500,
    principal: Principal | None = None,
) -> Subgraph:
    if not seeds or max_hops < 1:
        return Subgraph()

    valid_clause = "e.valid_time @> now()" if not as_of_valid else "e.valid_time @> CAST(:vt AS timestamptz)"

    match direction:
        case "out":
            forward = "e.subject_id = w.id"
            next_id = "e.object_id"
        case "in":
            forward = "e.object_id = w.id"
            next_id = "e.subject_id"
        case _:
            forward = "(e.subject_id = w.id OR e.object_id = w.id)"
            next_id = ("CASE WHEN e.subject_id = w.id "
                       "THEN e.object_id ELSE e.subject_id END")

    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "seeds": seeds,
        "max_hops": max_hops,
        "max_nodes": max_nodes,
    }
    predicate_filter = ""
    if predicate_slugs:
        params["predicates"] = predicate_slugs
        predicate_filter = (
            "AND EXISTS (SELECT 1 FROM relation_type rt "
            " WHERE rt.id = e.predicate_id AND rt.slug = ANY(:predicates))"
        )

    if as_of_valid:
        params["vt"] = as_of_valid

    # ACL filter — restricts both the traversal walker AND the final
    # edge fetch. A user with no identity bridge sees only the connected
    # component reachable via in-workspace (no-source) edges. That's the
    # correct semantics: traversal can't leak edges past an ACL boundary.
    acl_filter = ""
    if principal is not None:
        acl_clause = edge_visibility_clause(principal, edge_alias="e")
        acl_filter = f"AND ({acl_clause.text})"
        for key, value in acl_clause._bindparams.items():
            params[key] = value.value

    sql = f"""
    WITH RECURSIVE walk (id, distance, path) AS (
      SELECT id, 0, ARRAY[id] FROM entity
      WHERE workspace_id = :workspace_id
        AND id::text = ANY(:seeds)
        AND deleted_at IS NULL

      UNION ALL

      SELECT ({next_id})::uuid AS id, w.distance + 1, w.path || ({next_id})::uuid
      FROM walk w
      JOIN edge e ON {forward}
        AND e.workspace_id = :workspace_id
        AND upper(e.sys_time) = 'infinity'
        AND {valid_clause}
        {predicate_filter}
        {acl_filter}
      WHERE w.distance < :max_hops
        AND NOT (({next_id})::uuid = ANY(w.path))
    )
    SELECT DISTINCT ON (ent.id)
      ent.id::text AS id, ent.iri, ent.canonical, et.slug AS type_slug,
      MIN(w.distance) OVER (PARTITION BY ent.id) AS distance
    FROM walk w
    JOIN entity ent ON ent.id = w.id AND ent.deleted_at IS NULL
    JOIN entity_type et ON et.id = ent.type_id
    LIMIT :max_nodes
    """

    rows = await session.execute(text(sql), params)
    nodes = [
        GraphNode(
            id=r["id"], type=r["type_slug"], canonical=r["canonical"],
            iri=r["iri"], distance=int(r["distance"]),
        )
        for r in rows.mappings()
    ]

    if type_slugs:
        nodes = [n for n in nodes if n.type in type_slugs or n.id in seeds]

    if not nodes:
        return Subgraph()

    node_ids = [n.id for n in nodes]
    edge_rows = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id, e.subject_id::text AS subject_id,
                   e.object_id::text AS object_id, rt.slug AS predicate,
                   e.fact AS fact,
                   lower(e.valid_time)::text AS valid_from,
                   CASE WHEN upper(e.valid_time) = 'infinity' THEN NULL
                        ELSE upper(e.valid_time)::text END AS valid_to
            FROM edge e
            JOIN relation_type rt ON rt.id = e.predicate_id
            WHERE e.workspace_id = :workspace_id
              AND upper(e.sys_time) = 'infinity'
              AND {valid_clause}
              AND e.subject_id::text = ANY(:node_ids)
              AND e.object_id::text = ANY(:node_ids)
              {("AND rt.slug = ANY(:predicates)" if predicate_slugs else "")}
              {acl_filter}
            """
        ),
        {**params, "node_ids": node_ids},
    )
    edges = [
        GraphEdge(
            id=r["id"], subject_id=r["subject_id"], object_id=r["object_id"],
            predicate=r["predicate"], fact=r["fact"],
            valid_from=r["valid_from"], valid_to=r["valid_to"],
        )
        for r in edge_rows.mappings()
    ]

    return Subgraph(nodes=nodes, edges=edges)
