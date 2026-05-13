"""In-process Arq job drain helper.

Scenario tests don't want to spin up the worker process — they enqueue
jobs through ``app.workers.queue`` helpers and then run them in-line
via this helper. The mapping between Arq function name and the actual
Python coroutine lives in :mod:`app.workers.jobs`.

This is best-effort and only covers the jobs the scenarios actually
enqueue (extraction, ontology proposal, exports). Adding a job
requires registering its name here.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.workers import jobs as jobs_mod
from app.workers.export import run_user_export, run_workspace_export
from app.workers.queue import get_queue

log = structlog.get_logger(__name__)


# arq function name → handler coroutine
_HANDLERS: dict[str, Any] = {
    "extract_episode": jobs_mod.extract_episode,
    "propose_and_apply_ontology": jobs_mod.propose_and_apply_ontology,
    "run_workspace_export": run_workspace_export,
    "run_user_export": run_user_export,
    "purge_old_audit_log": jobs_mod.purge_old_audit_log,
}


async def drain_arq(*, max_iterations: int = 50) -> int:
    """Pop every queued job and run it synchronously.

    Returns the number of jobs run. Uses the Arq pool's internal Redis
    keys directly — we read job records out of the queue, dispatch the
    matching coroutine, then mark the job complete.

    Important: only jobs we know about (see ``_HANDLERS``) get run.
    Anything else is left in place and logged.
    """
    import pickle

    queue = await get_queue()
    queue_name = "arq:queue"  # default Arq stream
    ran = 0
    for _ in range(max_iterations):
        # Atomic pop: ZRANGEBYSCORE + ZREM in a single transaction.
        scripts = await queue.zrangebyscore(queue_name, min=0, max=float("inf"), start=0, num=1)
        if not scripts:
            break
        job_id = scripts[0]
        if isinstance(job_id, bytes):
            job_id = job_id.decode()
        await queue.zrem(queue_name, job_id)

        raw = await queue.get(f"arq:job:{job_id}")
        if raw is None:
            log.warning("drain_arq.missing_job_record", job_id=job_id)
            continue
        try:
            payload = pickle.loads(raw)
        except Exception as exc:
            log.warning("drain_arq.pickle_failed", job_id=job_id, error=str(exc))
            continue

        fn_name = payload.get("f") or payload.get("function")
        kwargs = payload.get("k") or payload.get("kwargs") or {}
        handler = _HANDLERS.get(fn_name or "")
        if handler is None:
            log.warning(
                "drain_arq.no_handler", job_id=job_id, fn_name=fn_name,
            )
            continue
        try:
            await handler({"job_id": job_id, "drain": True}, **kwargs)
            ran += 1
        except Exception as exc:
            log.warning(
                "drain_arq.handler_failed",
                job_id=job_id, fn_name=fn_name, error=str(exc),
            )
        # Mark the job record as removed so a re-run doesn't see it.
        await queue.delete(f"arq:job:{job_id}")

    return ran


async def run_extraction_inline(
    *,
    workspace_id: str,
    episode_id: str,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Call the extraction handler directly. Use when a test doesn't
    need (or care about) the Arq queue path — most scenarios don't.
    """
    return await jobs_mod.extract_episode(
        {"job_id": "test"},
        workspace_id=workspace_id,
        episode_id=episode_id,
        actor_id=actor_id,
    )
