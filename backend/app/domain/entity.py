"""Entity domain service.

Entities are the nodes of the knowledge graph. Identity is uni-temporal
(stable) — history lives on edges and optionally entity_attribute. This
service owns CRUD, alias/embedding-based resolution, and owl:sameAs-style
merge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import ontology as ontology_mod
from app.domain.ontology import OntologyError
from app.llm.embedding import get_embedding_client
from app.llm.vector_utils import to_pg_vector


class EntityNotFoundError(Exception):
    pass


class EntityMergeUnsafeError(Exception):
    """Raised when ``merge_cluster`` refuses a merge that would touch
    too many entities connected by weak-confidence edges.

    The check is intentionally conservative: a customer should never be
    surprised by silent collapse of 12 entities into one. The caller can
    either lower the cluster size, raise edge confidence, or break the
    cluster up into pair-merges performed under explicit review.
    """

    pass


@dataclass
class Entity:
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


def _iri_for(workspace_id: str, entity_id: str) -> str:
    return f"urn:memory:ws:{workspace_id}:e:{entity_id}"


async def create(
    session: AsyncSession,
    *,
    workspace_id: str,
    type_ref: str,
    canonical: str,
    aliases: list[str] | None = None,
    summary: str | None = None,
    props: dict[str, Any] | None = None,
    created_by: str | None = None,
    embed: bool = True,
) -> Entity:
    type_def = await ontology_mod.get_entity_type(session, type_ref)
    if not type_def:
        raise OntologyError(f"entity type not found: {type_ref}")

    props_val = props or {}
    ontology_mod.validate_entity_props(type_def, props_val)

    entity_id = str(uuid4())
    iri = _iri_for(workspace_id, entity_id)

    summary_embedding: list[float] | None = None
    if embed and summary:
        try:
            summary_embedding = await get_embedding_client().embed_one(summary)
        except Exception:
            summary_embedding = None

    await session.execute(
        text(
            """
            INSERT INTO entity
              (id, workspace_id, type_id, iri, canonical, aliases, summary,
               summary_embedding, props, created_by)
            VALUES
              (:id, :workspace_id, :type_id, :iri, :canonical, :aliases, :summary,
               CAST(:summary_embedding AS vector), CAST(:props AS jsonb), :created_by)
            """
        ),
        {
            "id": entity_id,
            "workspace_id": workspace_id,
            "type_id": type_def.id,
            "iri": iri,
            "canonical": canonical,
            "aliases": aliases or [],
            "summary": summary,
            "summary_embedding": to_pg_vector(summary_embedding),
            "props": json.dumps(props_val),
            "created_by": created_by,
        },
    )

    fetched = await get(session, entity_id)
    if not fetched:
        raise EntityNotFoundError(entity_id)
    return fetched


async def update(
    session: AsyncSession,
    *,
    entity_id: str,
    patch: dict[str, Any],
    embed: bool = True,
) -> Entity:
    existing = await get(session, entity_id)
    if not existing:
        raise EntityNotFoundError(entity_id)

    # Patch is shallow-merged over props; top-level keys canonical/aliases/summary
    # are treated specially.
    canonical = patch.get("canonical", existing.canonical)
    aliases = patch.get("aliases", existing.aliases)
    summary = patch.get("summary", existing.summary)

    props_patch = {k: v for k, v in patch.items() if k not in {"canonical", "aliases", "summary", "props"}}
    # Allow explicit `props` key to replace wholesale; otherwise merge.
    if "props" in patch:
        props = dict(patch["props"])
    else:
        props = dict(existing.props)
        props.update(props_patch)

    type_def = await _load_type_by_id(session, existing.type_id)
    if type_def:
        ontology_mod.validate_entity_props(type_def, props)

    summary_embedding: list[float] | None = None
    if embed and summary and summary != existing.summary:
        try:
            summary_embedding = await get_embedding_client().embed_one(summary)
        except Exception:
            summary_embedding = None

    sets = ["canonical = :canonical", "aliases = :aliases", "summary = :summary",
            "props = CAST(:props AS jsonb)"]
    params = {
        "id": entity_id,
        "canonical": canonical,
        "aliases": aliases,
        "summary": summary,
        "props": json.dumps(props),
    }
    if summary_embedding is not None:
        sets.append("summary_embedding = CAST(:summary_embedding AS vector)")
        params["summary_embedding"] = to_pg_vector(summary_embedding)

    await session.execute(
        text(f"UPDATE entity SET {', '.join(sets)} WHERE id = :id"),
        params,
    )
    fetched = await get(session, entity_id)
    assert fetched is not None
    return fetched


async def soft_delete(session: AsyncSession, entity_id: str) -> None:
    await session.execute(
        text("UPDATE entity SET deleted_at = now() WHERE id = :id"),
        {"id": entity_id},
    )


async def get(session: AsyncSession, ref: str) -> Entity | None:
    """Resolve an entity by id, iri, or canonical (case-insensitive). Follows
    merged_into_id so callers always get the surviving entity.
    """
    result = await session.execute(
        text(
            """
            WITH target AS (
              SELECT id FROM entity
              WHERE (id::text = :ref OR iri = :ref OR canonical ILIKE :ref)
                AND deleted_at IS NULL
              ORDER BY
                CASE WHEN id::text = :ref OR iri = :ref THEN 0 ELSE 1 END
              LIMIT 1
            ),
            resolved AS (
              SELECT e.id FROM entity e, target t
              WHERE e.id = t.id
            )
            SELECT e.id::text, e.workspace_id::text, e.type_id::text, et.slug AS type_slug,
                   e.iri, e.canonical, e.aliases, e.summary, e.props,
                   e.merged_into_id::text, e.created_by::text,
                   e.created_at::text, e.updated_at::text
            FROM entity e
            JOIN entity_type et ON et.id = e.type_id
            WHERE e.id = (SELECT id FROM resolved)
            """
        ),
        {"ref": ref},
    )
    row = result.mappings().first()
    if not row:
        return None
    if row["merged_into_id"]:
        return await get(session, row["merged_into_id"])
    return _row_to_entity(row)


async def list_entities(
    session: AsyncSession,
    *,
    type_ref: str | None = None,
    query: str | None = None,
    include_subtypes: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[Entity]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    where = ["e.deleted_at IS NULL", "e.merged_into_id IS NULL"]

    if type_ref:
        if include_subtypes:
            ids = await ontology_mod.subtype_ids(session, type_ref)
            if not ids:
                return []
            params["type_ids"] = ids
            where.append("e.type_id = ANY(:type_ids)")
        else:
            tdef = await ontology_mod.get_entity_type(session, type_ref)
            if not tdef:
                return []
            params["type_id"] = tdef.id
            where.append("e.type_id = :type_id")

    if query:
        params["q"] = f"%{query}%"
        where.append("(e.canonical ILIKE :q OR :q = ANY(e.aliases))")

    sql = (
        "SELECT e.id::text, e.workspace_id::text, e.type_id::text, et.slug AS type_slug,"
        "       e.iri, e.canonical, e.aliases, e.summary, e.props,"
        "       e.merged_into_id::text, e.created_by::text,"
        "       e.created_at::text, e.updated_at::text "
        "FROM entity e JOIN entity_type et ON et.id = e.type_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY e.updated_at DESC LIMIT :limit OFFSET :offset"
    )
    result = await session.execute(text(sql), params)
    return [_row_to_entity(r) for r in result.mappings()]


async def resolve_by_alias(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    type_ref: str | None = None,
    similarity_threshold: float = 0.4,
    limit: int = 5,
) -> list[Entity]:
    """Candidate entities matching by canonical/alias similarity (trigram)."""
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "name": name,
        "threshold": similarity_threshold,
        "limit": limit,
    }
    extra = ""
    if type_ref:
        ids = await ontology_mod.subtype_ids(session, type_ref)
        if not ids:
            return []
        params["type_ids"] = ids
        extra = "AND e.type_id = ANY(:type_ids)"

    result = await session.execute(
        text(
            f"""
            SELECT e.id::text, e.workspace_id::text, e.type_id::text, et.slug AS type_slug,
                   e.iri, e.canonical, e.aliases, e.summary, e.props,
                   e.merged_into_id::text, e.created_by::text,
                   e.created_at::text, e.updated_at::text,
                   GREATEST(
                     similarity(e.canonical, :name),
                     COALESCE((SELECT MAX(similarity(a, :name)) FROM unnest(e.aliases) a), 0)
                   ) AS score
            FROM entity e
            JOIN entity_type et ON et.id = e.type_id
            WHERE e.workspace_id = :workspace_id
              AND e.deleted_at IS NULL AND e.merged_into_id IS NULL
              {extra}
              AND (similarity(e.canonical, :name) >= :threshold
                   OR EXISTS (SELECT 1 FROM unnest(e.aliases) a WHERE similarity(a, :name) >= :threshold))
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [_row_to_entity(r) for r in result.mappings()]


async def merge_entities(
    session: AsyncSession,
    *,
    survivor_id: str,
    loser_id: str,
    actor_kind: str = "user",
    actor_id: str | None = None,
) -> Entity:
    """Merge `loser` into `survivor`. Rewrites edges and marks the loser merged.

    Pair shape — for batch merges use ``merge_cluster`` (which runs the
    weak-cluster safeguard). Pair merges (cluster size 2) always pass
    the safeguard, so this is equivalent to calling ``merge_cluster``
    with one loser.
    """
    return await merge_cluster(
        session,
        survivor_id=survivor_id,
        loser_ids=[loser_id],
        actor_kind=actor_kind,
        actor_id=actor_id,
    )


async def merge_cluster(
    session: AsyncSession,
    *,
    survivor_id: str,
    loser_ids: list[str],
    actor_kind: str = "user",
    actor_id: str | None = None,
) -> Entity:
    """Merge each loser in ``loser_ids`` into ``survivor_id``.

    Before any edge rewrite, ``cluster_is_safe_to_merge`` runs on the
    full set of touched entity ids (survivor + losers). Refusals raise
    ``EntityMergeUnsafeError`` and the database is left untouched.

    The pair-merge call shape (one loser) always passes the safeguard
    because the cluster size threshold is generous.
    """
    if not loser_ids:
        raise ValueError("loser_ids must be non-empty")
    if survivor_id in loser_ids:
        raise ValueError("cannot merge an entity with itself")
    if len(set(loser_ids)) != len(loser_ids):
        raise ValueError("loser_ids must be unique")

    # Resolve workspace_id from the survivor so callers don't have to
    # pass it in; merge across workspaces is an explicit error.
    workspace_id = (
        await session.execute(
            text(
                "SELECT workspace_id::text FROM entity WHERE id = :id"
            ),
            {"id": survivor_id},
        )
    ).scalar_one_or_none()
    if workspace_id is None:
        raise EntityNotFoundError(survivor_id)

    # Reject cross-workspace merges loudly.
    ws_row = (
        await session.execute(
            text(
                "SELECT id::text FROM entity "
                "WHERE id = ANY(:ids) AND workspace_id <> CAST(:ws AS uuid)"
            ),
            {"ids": loser_ids, "ws": workspace_id},
        )
    ).first()
    if ws_row is not None:
        raise EntityMergeUnsafeError(
            f"cross-workspace merge rejected: entity {ws_row[0]} is in a "
            f"different workspace from survivor {survivor_id}"
        )

    # Safeguard: bail before any UPDATE runs.
    from app.domain import entity_resolver as resolver_mod

    cluster = [survivor_id, *loser_ids]
    safe, reason = await resolver_mod.cluster_is_safe_to_merge(
        session, workspace_id=workspace_id, entity_ids=cluster
    )
    if not safe:
        raise EntityMergeUnsafeError(
            f"cluster merge refused: {reason} "
            f"(cluster size={len(cluster)}, survivor={survivor_id})"
        )

    # Now perform the rewrites for each loser. Two UPDATEs per loser
    # because asyncpg rejects multi-statement execute().
    for loser_id in loser_ids:
        await session.execute(
            text(
                """
                UPDATE edge SET subject_id = :s
                WHERE subject_id = :l AND upper(sys_time) = 'infinity'
                """
            ),
            {"s": survivor_id, "l": loser_id},
        )
        await session.execute(
            text(
                """
                UPDATE edge SET object_id = :s
                WHERE object_id = :l AND upper(sys_time) = 'infinity'
                """
            ),
            {"s": survivor_id, "l": loser_id},
        )
        await session.execute(
            text(
                """
                UPDATE entity SET merged_into_id = :s
                WHERE id = :l AND merged_into_id IS NULL
                """
            ),
            {"s": survivor_id, "l": loser_id},
        )
        await session.execute(
            text(
                """
                INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                       target_kind, target_id, diff)
                VALUES (CAST(:ws AS uuid), :actor_kind, :actor_id, 'entity.merge',
                        'entity', CAST(:survivor_id AS uuid),
                        jsonb_build_object(
                          'survivor_id', CAST(:survivor_id AS text),
                          'loser_id', CAST(:loser_id AS text),
                          'cluster_size', CAST(:cluster_size AS int)
                        ))
                """
            ),
            {
                "ws": workspace_id,
                "actor_kind": actor_kind,
                "actor_id": actor_id,
                "survivor_id": survivor_id,
                "loser_id": loser_id,
                "cluster_size": len(cluster),
            },
        )

    survivor = await get(session, survivor_id)
    assert survivor is not None
    return survivor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_entity(row: Any) -> Entity:
    return Entity(
        id=row["id"],
        workspace_id=row["workspace_id"],
        type_id=row["type_id"],
        type_slug=row.get("type_slug"),
        iri=row["iri"],
        canonical=row["canonical"],
        aliases=list(row["aliases"] or []),
        summary=row["summary"],
        props=row["props"] or {},
        merged_into_id=row.get("merged_into_id"),
        created_by=row.get("created_by"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _load_type_by_id(session: AsyncSession, type_id: str):
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, name, slug, extends_id::text,
                   hierarchy::text, schema, ui_hints, description, system,
                   created_at::text, updated_at::text
            FROM entity_type WHERE id = :id AND deleted_at IS NULL
            """
        ),
        {"id": type_id},
    )
    row = result.mappings().first()
    if not row:
        return None
    from app.domain.ontology import EntityType
    return EntityType(
        id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
        slug=row["slug"], extends_id=row["extends_id"], hierarchy=row["hierarchy"],
        schema=row["schema"], ui_hints=row["ui_hints"], description=row["description"],
        system=row["system"], created_at=row["created_at"], updated_at=row["updated_at"],
    )
