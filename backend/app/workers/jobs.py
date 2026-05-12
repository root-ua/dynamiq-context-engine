"""Arq worker entrypoints.

One process runs as the FastAPI HTTP server; a sibling process
(`backend-worker` in docker-compose) pulls jobs from Redis.
"""
from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope

log = get_logger(__name__)


async def startup(ctx: dict) -> None:
    configure_logging(get_settings().log_level)
    log.info("arq.worker.startup")


async def shutdown(ctx: dict) -> None:
    log.info("arq.worker.shutdown")


async def extract_episode(ctx: dict, *, workspace_id: str, episode_id: str, actor_id: str | None = None) -> dict[str, Any]:
    from app.extraction.pipeline import process_episode

    async with session_scope(workspace_id=workspace_id, user_id=actor_id) as session:
        result = await process_episode(session, episode_id=episode_id, actor_id=actor_id)

    return {
        "episode_id": result.episode_id,
        "created_entities": result.created_entities,
        "created_edges": result.created_edges,
        "resolved_entities": result.resolved_entities,
        "ontology_extended_types": result.ontology_extended_types,
        "ontology_extended_relations": result.ontology_extended_relations,
        "errors": result.errors,
    }


async def propose_and_apply_ontology(
    ctx: dict,
    *,
    workspace_id: str,
    episode_ids: list[str],
    actor_id: str | None,
    apply: bool,
) -> dict[str, Any]:
    from app.domain import auto_ontology

    async with session_scope(workspace_id=workspace_id, user_id=actor_id) as session:
        samples: list[str] = []
        for eid in episode_ids:
            row = await session.execute(
                _sql("SELECT content_text FROM episode WHERE id = :id"),
                {"id": eid},
            )
            v = row.scalar()
            if v:
                samples.append(v)

        proposal = await auto_ontology.propose_ontology(
            session, workspace_id=workspace_id, samples=samples
        )

        applied = None
        if apply:
            applied = await auto_ontology.apply_proposal(
                session,
                workspace_id=workspace_id,
                proposal=proposal,
                actor_id=actor_id,
            )

    out: dict[str, Any] = {"proposal": proposal.model_dump()}
    if applied:
        out["applied"] = {
            "created_types": applied.created_types,
            "created_relations": applied.created_relations,
            "skipped_types": applied.skipped_types,
            "skipped_relations": applied.skipped_relations,
        }
    return out


def _sql(q: str):
    from sqlalchemy import text
    return text(q)


from app.workers.crawler import crawl_initial, crawl_incremental, refresh_acl


class WorkerSettings:
    functions = [
        extract_episode,
        propose_and_apply_ontology,
        crawl_initial,
        crawl_incremental,
        refresh_acl,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    keep_result_forever = False
    max_jobs = 8
