from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.rest.schemas import EpisodeCreate, EpisodeOut
from app.auth.deps import CurrentPrincipal, DbSession
from app.domain import episode as episode_mod
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
    items = await episode_mod.list_episodes(
        session, workspace_id=principal.workspace_id,
        status=status, limit=limit, offset=offset,
    )
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
async def get(episode_id: str, _: CurrentPrincipal, session: DbSession) -> EpisodeOut:
    ep = await episode_mod.get(session, episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    return _to_out(ep)


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
