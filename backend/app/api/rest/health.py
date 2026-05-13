"""Liveness vs readiness split.

* ``GET /health``  — process is up. Constant-time, no I/O. Used by
  Render's basic health-check and any uptime monitor.
* ``GET /ready``   — dependencies are reachable (Postgres, Redis).
  Returns 503 if any dependency is down. Used by orchestrators that want
  to drain traffic before a slow restart.
* ``GET /health/db`` — kept for back-compat; equivalent to the DB leg of
  ``/ready``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import session_scope

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness — process is alive."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness — all dependencies are reachable.

    Returns 503 with the failed component name when something is down so
    the orchestrator can hold off traffic until recovery.
    """
    # DB check.
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("ready.db_check_failed", error=str(exc))
        raise HTTPException(
            503, detail={"status": "down", "component": "postgres"}
        ) from exc

    # Redis check (best-effort: skip if URL not set).
    settings = get_settings()
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.ping()
        await pool.close()
    except Exception as exc:
        log.warning("ready.redis_check_failed", error=str(exc))
        raise HTTPException(
            503, detail={"status": "down", "component": "redis"}
        ) from exc

    return {"status": "ready"}


@router.get("/health/db")
async def health_db() -> dict[str, str | int]:
    async with session_scope() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar_one()
    return {"status": "ok", "postgres": int(value)}
