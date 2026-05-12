"""Source documents — connector-ingested episodes, ACL-filtered.

Lets a workspace member browse the documents the connectors have
imported on their behalf. The list is automatically filtered through
``episode_visibility_clause(principal)`` so callers only see episodes
backed by source-system permissions they hold.

Detail view also returns the derived edges for the episode (also
ACL-filtered, although in practice if you can see the episode you can
see all edges sourced from it).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.acl import edge_visibility_clause, episode_visibility_clause
from app.auth.deps import CurrentPrincipal, DbSession

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceEpisodeOut(BaseModel):
    id: str
    connector_kind: str
    title: str
    external_id: str
    external_url: str | None
    mime_type: str | None
    last_modified_external: str | None
    ingested_at: str


class SourceEdgeOut(BaseModel):
    id: str
    fact: str
    subject: str
    object: str
    predicate: str
    valid_from: str | None
    valid_to: str | None


class SourceEpisodeDetail(SourceEpisodeOut):
    derived_edges: list[SourceEdgeOut]
    acl: list[dict[str, Any]] | None  # only populated for owners/admins


def _row_to_summary(row: dict[str, Any]) -> SourceEpisodeOut:
    title = (row.get("content") or {}).get("title") if isinstance(row.get("content"), dict) else None
    return SourceEpisodeOut(
        id=row["id"],
        connector_kind=row["connector_kind"],
        title=title or row.get("external_id") or "",
        external_id=row["external_id"],
        external_url=row.get("external_url"),
        mime_type=row.get("mime_type"),
        last_modified_external=row.get("last_modified_external"),
        ingested_at=row["ingested_at"],
    )


@router.get("")
async def list_sources(
    principal: CurrentPrincipal,
    session: DbSession,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[SourceEpisodeOut]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    clause = episode_visibility_clause(principal, episode_alias="episode")
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "ws": principal.workspace_id,
    }
    for k, v in clause._bindparams.items():
        params[k] = v.value

    # Explicit workspace_id filter on both episode and ci. RLS policies
    # exist on these tables, but the ``memory`` DB role has BYPASSRLS so
    # relying on RLS alone leaks across workspaces. Filter explicitly to
    # match the rest of the codebase's pattern.
    sql = f"""
      SELECT episode.id::text AS id,
             ci.connector_kind AS connector_kind,
             episode.content AS content,
             episode.external_id AS external_id,
             episode.external_url AS external_url,
             episode.mime_type AS mime_type,
             episode.last_modified_external::text AS last_modified_external,
             episode.ingested_at::text AS ingested_at
      FROM episode
      JOIN connector_instance ci ON ci.id = episode.connector_instance_id
      WHERE episode.workspace_id = CAST(:ws AS uuid)
        AND ci.workspace_id = CAST(:ws AS uuid)
        AND episode.connector_instance_id IS NOT NULL
        AND episode.deleted_at IS NULL
        AND ci.deleted_at IS NULL
        AND ({clause.text})
      ORDER BY episode.ingested_at DESC
      LIMIT :limit OFFSET :offset
    """
    result = await session.execute(text(sql), params)
    return [_row_to_summary(dict(r)) for r in result.mappings()]


@router.get("/{episode_id}")
async def get_source(
    episode_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> SourceEpisodeDetail:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    ep_clause = episode_visibility_clause(principal, episode_alias="episode")
    ep_params: dict[str, Any] = {
        "id": episode_id,
        "ws": principal.workspace_id,
    }
    for k, v in ep_clause._bindparams.items():
        ep_params[k] = v.value

    ep_sql = f"""
      SELECT episode.id::text AS id,
             ci.connector_kind AS connector_kind,
             episode.content AS content,
             episode.external_id AS external_id,
             episode.external_url AS external_url,
             episode.mime_type AS mime_type,
             episode.last_modified_external::text AS last_modified_external,
             episode.ingested_at::text AS ingested_at,
             episode.acl AS acl
      FROM episode
      JOIN connector_instance ci ON ci.id = episode.connector_instance_id
      WHERE episode.id = CAST(:id AS uuid)
        AND episode.workspace_id = CAST(:ws AS uuid)
        AND ci.workspace_id = CAST(:ws AS uuid)
        AND ci.deleted_at IS NULL
        AND episode.connector_instance_id IS NOT NULL
        AND episode.deleted_at IS NULL
        AND ({ep_clause.text})
    """
    ep_row = (await session.execute(text(ep_sql), ep_params)).mappings().first()
    if ep_row is None:
        raise HTTPException(404, "source not found")

    # Pull derived edges (also ACL-filtered).
    edge_clause = edge_visibility_clause(principal, edge_alias="e")
    edge_params: dict[str, Any] = {"src": episode_id}
    for k, v in edge_clause._bindparams.items():
        edge_params[k] = v.value

    edges = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id, e.fact AS fact,
                   s.canonical AS subject, o.canonical AS object,
                   rt.slug AS predicate,
                   lower(e.valid_time)::text AS valid_from,
                   CASE WHEN upper(e.valid_time) = 'infinity' THEN NULL
                        ELSE upper(e.valid_time)::text END AS valid_to
            FROM edge e
            JOIN entity s ON s.id = e.subject_id
            JOIN entity o ON o.id = e.object_id
            JOIN relation_type rt ON rt.id = e.predicate_id
            WHERE e.source_id = CAST(:src AS uuid)
              AND upper(e.sys_time) = 'infinity'
              AND ({edge_clause.text})
            ORDER BY lower(e.valid_time) DESC
            LIMIT 200
            """
        ),
        edge_params,
    )

    derived = [SourceEdgeOut(**dict(r)) for r in edges.mappings()]
    summary = _row_to_summary(dict(ep_row))

    # ACL exposed only to owners/admins so members can't enumerate
    # source-system principals.
    acl_payload = None
    if principal.role in ("owner", "admin"):
        acl_payload = ep_row.get("acl")

    return SourceEpisodeDetail(
        **summary.model_dump(),
        derived_edges=derived,
        acl=acl_payload,
    )
