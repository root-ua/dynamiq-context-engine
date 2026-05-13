"""Thin Arq enqueue helpers for use from HTTP handlers."""
from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def enqueue_extraction(
    *, workspace_id: str, episode_id: str, actor_id: str | None = None
) -> None:
    queue = await get_queue()
    await queue.enqueue_job(
        "extract_episode",
        workspace_id=workspace_id,
        episode_id=episode_id,
        actor_id=actor_id,
    )


async def enqueue_ontology_proposal(
    *, workspace_id: str, episode_ids: list[str], actor_id: str | None, apply: bool
) -> str:
    queue = await get_queue()
    job = await queue.enqueue_job(
        "propose_and_apply_ontology",
        workspace_id=workspace_id,
        episode_ids=episode_ids,
        actor_id=actor_id,
        apply=apply,
    )
    return job.job_id if job else ""


async def enqueue_workspace_export(*, job_id: str, workspace_id: str) -> str:
    queue = await get_queue()
    job = await queue.enqueue_job(
        "run_workspace_export",
        job_id=job_id,
        workspace_id=workspace_id,
    )
    return job.job_id if job else ""


async def enqueue_user_export(*, job_id: str, user_id: str) -> str:
    queue = await get_queue()
    job = await queue.enqueue_job(
        "run_user_export",
        job_id=job_id,
        user_id=user_id,
    )
    return job.job_id if job else ""
