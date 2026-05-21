"""Arq worker entrypoints.

One process runs as the FastAPI HTTP server; a sibling process
(`backend-worker` in docker-compose) pulls jobs from Redis.

Graceful shutdown: on SIGTERM we set a drain flag in the Arq context so
the worker stops accepting new jobs while in-flight jobs finish. The
flag is honored by Arq's internal scheduler via ``ctx["drain_until"]``.
Once ``WORKER_DRAIN_SECONDS`` elapses, the process exits — orchestrators
that send a second SIGTERM after that get a clean exit too.
"""
from __future__ import annotations

import asyncio
import signal
import time
from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope

log = get_logger(__name__)


def _install_signal_handlers(ctx: dict) -> None:
    """Wire SIGTERM/SIGINT to flip ``ctx['draining']`` and cap the wait."""
    loop = asyncio.get_event_loop()

    def _drain(signame: str) -> None:
        if ctx.get("draining"):
            log.info("arq.worker.drain.repeat_signal", signal=signame)
            return
        seconds = get_settings().worker_drain_seconds
        ctx["draining"] = True
        ctx["drain_until"] = time.monotonic() + seconds
        log.info(
            "arq.worker.drain.start",
            signal=signame,
            seconds=seconds,
        )
        # Schedule a hard stop so we exit cleanly even if a job hangs.
        loop.call_later(seconds, _force_exit)

    def _force_exit() -> None:
        log.info("arq.worker.drain.force_exit")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    try:
        loop.add_signal_handler(signal.SIGTERM, _drain, "SIGTERM")
        loop.add_signal_handler(signal.SIGINT, _drain, "SIGINT")
    except (NotImplementedError, RuntimeError):
        # Not all event loops (e.g. Windows ProactorEventLoop) support
        # add_signal_handler. The worker survives without the
        # enhancement.
        log.info("arq.worker.signal_handlers_unavailable")


async def startup(ctx: dict) -> None:
    configure_logging(get_settings().log_level)
    ctx["draining"] = False
    _install_signal_handlers(ctx)
    log.info("arq.worker.startup")


async def shutdown(ctx: dict) -> None:
    log.info("arq.worker.shutdown", draining=bool(ctx.get("draining")))


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


async def purge_old_audit_log(ctx: dict) -> dict[str, Any]:
    """Daily-ish cron: trim audit_log to the retention window.

    Idempotent — running it twice in a row is a no-op.
    """
    settings = get_settings()
    if settings.audit_log_retention_days <= 0:
        return {"purged": 0, "skipped": "retention disabled"}

    sql = _sql(
        """
        DELETE FROM audit_log
        WHERE created_at < (now() - (CAST(:days AS int) || ' days')::interval)
        """
    )
    async with session_scope() as session:
        result = await session.execute(
            sql, {"days": settings.audit_log_retention_days}
        )
        purged = result.rowcount or 0
    log.info(
        "audit_log.purge.completed",
        purged=purged,
        retention_days=settings.audit_log_retention_days,
    )
    return {"purged": purged}


from arq import cron  # noqa: E402  (registered after job fns are defined)

from app.workers.export import (  # noqa: E402
    run_user_export,
    run_workspace_export,
)
from app.integrations.google.sync import sync_google_docs  # noqa: E402


class WorkerSettings:
    functions = [
        extract_episode,
        propose_and_apply_ontology,
        run_workspace_export,
        run_user_export,
        purge_old_audit_log,
        sync_google_docs,
    ]
    cron_jobs = [
        # 03:17 UTC daily; off-peak.
        cron(purge_old_audit_log, hour=3, minute=17, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    keep_result_forever = False
    max_jobs = 8
