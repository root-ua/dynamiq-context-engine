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
from app.auth.external_acl import resolve_user_identities
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

    # ``clock_timestamp()`` so a fact inserted earlier in the same
    # transaction is visible — ``now()`` returns the transaction start
    # time, which would silently exclude it.
    valid_clause = (
        "e.valid_time @> clock_timestamp()"
        if not as_of_valid
        else "e.valid_time @> CAST(:vt AS timestamptz)"
    )

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
        # asyncpg needs a datetime, not a raw ISO string — even though the
        # SQL CASTs it. See the same fix in whole_graph().
        from datetime import datetime
        params["vt"] = datetime.fromisoformat(as_of_valid.replace("Z", "+00:00"))

    # ACL filter — restricts both the traversal walker AND the final
    # edge fetch. A user with no identity bridge sees only the connected
    # component reachable via in-workspace (no-source) edges. That's the
    # correct semantics: traversal can't leak edges past an ACL boundary.
    acl_filter = ""
    if principal is not None:
        identities = await resolve_user_identities(session, principal)
        acl_clause = edge_visibility_clause(
            principal, edge_alias="e", identities=identities
        )
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


async def whole_graph(
    session: AsyncSession,
    *,
    workspace_id: str,
    max_nodes: int = 500,
    principal: Principal | None = None,
    type_slugs: list[str] | None = None,
    predicate_slugs: list[str] | None = None,
    as_of_valid: str | None = None,
) -> Subgraph:
    """Return every live edge in the workspace, with the entities they
    connect, capped at ``max_nodes`` entities.

    Optional filters:
      - ``type_slugs``: restrict to entities of these types.
      - ``predicate_slugs``: restrict to edges with these relation slugs.
      - ``as_of_valid``: bi-temporal as-of — return edges whose
        ``valid_time`` contains this timestamp instead of clock_timestamp().

    Edges are bounded to those whose both endpoints landed in the node set,
    so the response is a self-contained subgraph.
    """
    type_filter = ""
    node_params: dict[str, Any] = {"ws": workspace_id, "max_nodes": max_nodes}
    if type_slugs:
        type_filter = "AND et.slug = ANY(:type_slugs)"
        node_params["type_slugs"] = type_slugs

    node_rows = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id,
                   COALESCE(et.slug, 'thing') AS type,
                   e.canonical AS canonical,
                   e.iri AS iri
            FROM entity e
            LEFT JOIN entity_type et ON et.id = e.type_id
            WHERE e.workspace_id = CAST(:ws AS uuid)
              AND e.deleted_at IS NULL
              AND e.merged_into_id IS NULL
              {type_filter}
            ORDER BY e.created_at DESC
            LIMIT :max_nodes
            """
        ),
        node_params,
    )
    nodes = [
        GraphNode(
            id=r["id"], type=r["type"], canonical=r["canonical"],
            iri=r["iri"], distance=0,
        )
        for r in node_rows.mappings()
    ]
    if not nodes:
        return Subgraph(nodes=[], edges=[])

    primary_node_ids = [n.id for n in nodes]
    # If a type filter is active, edges connect filtered entities to
    # potentially-unfiltered ones (e.g. project → person). We want to
    # show those edges, so we also need to pull in the "other side"
    # entities even if their type doesn't match. Without this, filtering
    # to "project" would return 0 edges because no project-to-project
    # edges exist.
    node_ids = list(primary_node_ids)
    params: dict[str, Any] = {"ws": workspace_id, "node_ids": node_ids}

    # Bi-temporal: default to "true right now"; allow caller to ask
    # "true at <past timestamp>" instead. The chosen instant is intersected
    # with each edge's valid_time range via the `@>` operator.
    #
    # asyncpg refuses raw strings for timestamptz binds even when the SQL
    # CASTs them, so we parse to a datetime here. Accept ISO-8601 with
    # optional 'Z' for UTC (the frontend sends ISO strings from new Date().toISOString()).
    valid_clause = (
        "e.valid_time @> clock_timestamp()"
        if not as_of_valid
        else "e.valid_time @> CAST(:vt AS timestamptz)"
    )
    if as_of_valid:
        from datetime import datetime
        params["vt"] = datetime.fromisoformat(as_of_valid.replace("Z", "+00:00"))

    predicate_filter = ""
    if predicate_slugs:
        predicate_filter = "AND rt.slug = ANY(:predicate_slugs)"
        params["predicate_slugs"] = predicate_slugs

    acl_filter = ""
    if principal is not None:
        identities = await resolve_user_identities(session, principal)
        acl_clause = edge_visibility_clause(
            principal, edge_alias="e", identities=identities
        )
        acl_filter = f"AND ({acl_clause.text})"
        for key, value in acl_clause._bindparams.items():
            params[key] = value.value

    # AT LEAST ONE endpoint must be in the filtered node set (was: both).
    # This is what gives us the "show this type and its neighbors" UX.
    # We then bring in the other-side entities as "context" nodes.
    edge_rows = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id,
                   e.subject_id::text AS subject_id,
                   e.object_id::text AS object_id,
                   rt.slug AS predicate,
                   COALESCE(e.fact, '') AS fact,
                   lower(e.valid_time)::text AS valid_from,
                   CASE
                     WHEN upper(e.valid_time) IS NULL OR upper(e.valid_time) = 'infinity'::timestamptz
                     THEN NULL
                     ELSE upper(e.valid_time)::text
                   END AS valid_to
            FROM edge e
            JOIN relation_type rt ON rt.id = e.predicate_id
            WHERE e.workspace_id = CAST(:ws AS uuid)
              AND upper(e.sys_time) = 'infinity'::timestamptz
              AND {valid_clause}
              AND (e.subject_id::text = ANY(:node_ids)
                   OR e.object_id::text = ANY(:node_ids))
              {predicate_filter}
              {acl_filter}
            """
        ),
        params,
    )
    edges = [
        GraphEdge(
            id=r["id"], subject_id=r["subject_id"], object_id=r["object_id"],
            predicate=r["predicate"], fact=r["fact"],
            valid_from=r["valid_from"], valid_to=r["valid_to"],
        )
        for r in edge_rows.mappings()
    ]

    # Pull in any "context" nodes — endpoints referenced by edges but
    # not already in the primary node set (e.g. when type_slugs filtered
    # to 'project' but a project is linked to a 'person' that didn't
    # match the filter). Without this the frontend would render orphan
    # edge endpoints.
    primary_ids_set = set(primary_node_ids)
    missing_ids: list[str] = []
    seen: set[str] = set()
    for e in edges:
        for end in (e.subject_id, e.object_id):
            if end not in primary_ids_set and end not in seen:
                seen.add(end)
                missing_ids.append(end)

    if missing_ids:
        ctx_rows = await session.execute(
            text(
                """
                SELECT e.id::text AS id,
                       COALESCE(et.slug, 'thing') AS type,
                       e.canonical AS canonical,
                       e.iri AS iri
                FROM entity e
                LEFT JOIN entity_type et ON et.id = e.type_id
                WHERE e.id::text = ANY(:ids)
                  AND e.deleted_at IS NULL AND e.merged_into_id IS NULL
                """
            ),
            {"ids": missing_ids},
        )
        for r in ctx_rows.mappings():
            nodes.append(
                GraphNode(
                    id=r["id"], type=r["type"], canonical=r["canonical"],
                    iri=r["iri"], distance=1,  # 1-hop "context" marker
                )
            )

    return Subgraph(nodes=nodes, edges=edges)
