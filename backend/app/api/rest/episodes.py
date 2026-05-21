from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.api.content_negotiation import accept_jsonld
from app.api.rest.schemas import EpisodeCreate, EpisodeOut
from app.auth.acl import edge_visibility_clause, episode_visibility_clause
from app.auth.deps import CurrentPrincipal, DbSession
from app.auth.external_acl import resolve_user_identities
from app.domain import episode as episode_mod
from app.jsonld import to_jsonld_episode
from app.workers.queue import enqueue_extraction

router = APIRouter(prefix="/episodes", tags=["episodes"])


@router.get("")
async def list_episodes(
    principal: CurrentPrincipal,
    session: DbSession,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
) -> list[EpisodeOut]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    # Post-filter the page by source ACL. The underlying domain helper
    # doesn't take ACL yet — adding it would touch a load-bearing file —
    # so we filter in Python. Fine for a paginated list, would be wrong
    # for unbounded scans.
    items = await episode_mod.list_episodes(
        session, workspace_id=principal.workspace_id,
        status=status, limit=limit, offset=offset,
    )
    if principal.kind == "user":
        visible_ids = await _visible_episode_ids(
            session, [e.id for e in items], principal
        )
        items = [e for e in items if e.id in visible_ids]
    return [_to_out(e) for e in items]


@router.post("", status_code=201)
async def create(
    payload: EpisodeCreate, principal: CurrentPrincipal, session: DbSession,
) -> EpisodeOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    ep = await episode_mod.add_episode(
        session,
        workspace_id=principal.workspace_id,
        content=payload.content,
        source_kind=payload.source_kind,
        source_ref=payload.source_ref,
        occurred_at=payload.occurred_at,
        created_by=principal.user_id,
    )

    if payload.extract:
        await enqueue_extraction(
            workspace_id=principal.workspace_id,
            episode_id=ep.id,
            actor_id=principal.user_id,
        )

    return _to_out(ep)


@router.get("/{episode_id}")
async def get(
    episode_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | EpisodeOut:
    # Visibility check: hide the episode entirely if Drive ACL excludes
    # this user. Returning 404 (not 403) is intentional — leaking the
    # existence of restricted episodes would itself be an information leak.
    if not await _episode_visible(session, episode_id, principal):
        raise HTTPException(404, "episode not found")
    ep = await episode_mod.get(session, episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    if jsonld:
        return to_jsonld_episode(ep)
    return _to_out(ep)


@router.get("/{episode_id}/extracted")
async def extracted(
    episode_id: str, principal: CurrentPrincipal, session: DbSession,
) -> dict[str, Any]:
    """Return entities + live edges sourced from this episode.

    Entities are the union of subjects and objects of those edges.
    Filtered by source ACL — if the user can't see the episode, the
    endpoint returns 404. Otherwise edges are also ACL-filtered (an
    edge whose source episode is invisible is omitted, even when a
    seed-rooted query would otherwise return it via this endpoint).
    """
    if not await _episode_visible(session, episode_id, principal):
        raise HTTPException(404, "episode not found")
    ep = await episode_mod.get(session, episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")

    params: dict[str, Any] = {"eid": episode_id}
    acl_filter = ""
    identities = await resolve_user_identities(session, principal)
    clause = edge_visibility_clause(
        principal, edge_alias="e", identities=identities
    )
    if clause.text != "TRUE":
        acl_filter = f"AND ({clause.text})"
        for k, v in clause._bindparams.items():
            params[k] = v.value

    edge_rows = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id,
                   e.subject_id::text AS subject_id,
                   e.object_id::text AS object_id,
                   rt.slug AS predicate,
                   e.fact AS fact,
                   lower(e.valid_time)::text AS valid_from,
                   CASE WHEN upper(e.valid_time) = 'infinity'::timestamptz
                        THEN NULL ELSE upper(e.valid_time)::text END AS valid_to,
                   s.canonical AS subject_canonical,
                   st.slug AS subject_type,
                   o.canonical AS object_canonical,
                   ot.slug AS object_type
            FROM edge e
            JOIN relation_type rt ON rt.id = e.predicate_id
            JOIN entity s ON s.id = e.subject_id
            JOIN entity o ON o.id = e.object_id
            LEFT JOIN entity_type st ON st.id = s.type_id
            LEFT JOIN entity_type ot ON ot.id = o.type_id
            WHERE e.source_id = CAST(:eid AS uuid)
              AND e.source_kind = 'episode'
              AND upper(e.sys_time) = 'infinity'::timestamptz
              {acl_filter}
            ORDER BY e.created_at
            """
        ),
        params,
    )
    edges = [dict(r) for r in edge_rows.mappings()]

    entity_ids: list[str] = []
    seen: set[str] = set()
    for e in edges:
        for key in ("subject_id", "object_id"):
            if e[key] not in seen:
                seen.add(e[key])
                entity_ids.append(e[key])

    entities: list[dict[str, Any]] = []
    if entity_ids:
        ent_rows = await session.execute(
            text(
                """
                SELECT en.id::text AS id, en.canonical AS canonical,
                       COALESCE(et.slug, 'thing') AS type_slug
                FROM entity en
                LEFT JOIN entity_type et ON et.id = en.type_id
                WHERE en.id::text = ANY(:ids)
                """
            ),
            {"ids": entity_ids},
        )
        by_id = {r["id"]: dict(r) for r in ent_rows.mappings()}
        entities = [by_id[i] for i in entity_ids if i in by_id]

    return {"episode_id": episode_id, "entities": entities, "edges": edges}


@router.post("/{episode_id}/reprocess", status_code=202)
async def reprocess(
    episode_id: str, principal: CurrentPrincipal, session: DbSession,
) -> dict[str, str]:
    ep = await episode_mod.get(session, episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    await enqueue_extraction(
        workspace_id=ep.workspace_id, episode_id=ep.id, actor_id=principal.user_id
    )
    return {"status": "queued"}


def _to_out(ep: episode_mod.Episode) -> EpisodeOut:
    return EpisodeOut(
        id=ep.id, workspace_id=ep.workspace_id,
        source_kind=ep.source_kind, source_ref=ep.source_ref,
        occurred_at=ep.occurred_at, ingested_at=ep.ingested_at,
        content_text=ep.content_text, processing_status=ep.processing_status,
        processing_error=ep.processing_error,
    )


async def _episode_visible(
    session: DbSession, episode_id: str, principal: CurrentPrincipal
) -> bool:
    """Single-episode visibility check, used by detail endpoints.

    Service principals always pass. User principals get filtered through
    the source ACL predicate; one DB hit.
    """
    if principal.kind != "user":
        return True
    identities = await resolve_user_identities(session, principal)
    clause = episode_visibility_clause(
        principal, episode_alias="ep", identities=identities
    )
    if clause.text == "ep.deleted_at IS NULL":
        return True
    params = {"id": episode_id}
    for k, v in clause._bindparams.items():
        params[k] = v.value
    row = await session.execute(
        text(
            f"SELECT 1 FROM episode ep WHERE ep.id = CAST(:id AS uuid) "
            f"AND ({clause.text}) LIMIT 1"
        ),
        params,
    )
    return row.first() is not None


async def _visible_episode_ids(
    session: DbSession,
    episode_ids: list[str],
    principal: CurrentPrincipal,
) -> set[str]:
    """Return the subset of ``episode_ids`` visible to the caller."""
    if not episode_ids or principal.kind != "user":
        return set(episode_ids)
    identities = await resolve_user_identities(session, principal)
    clause = episode_visibility_clause(
        principal, episode_alias="ep", identities=identities
    )
    if clause.text == "ep.deleted_at IS NULL":
        return set(episode_ids)
    params: dict[str, Any] = {"ids": episode_ids}
    for k, v in clause._bindparams.items():
        params[k] = v.value
    rows = await session.execute(
        text(
            f"SELECT ep.id::text AS id FROM episode ep "
            f"WHERE ep.id::text = ANY(:ids) AND ({clause.text})"
        ),
        params,
    )
    return {r["id"] for r in rows.mappings()}
