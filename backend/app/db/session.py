from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.postgres_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            future=True,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope(
    *,
    workspace_id: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
    bypass_external_acl: bool = False,
) -> AsyncIterator[AsyncSession]:
    """Open a transaction-scoped AsyncSession with RLS session vars applied.

    The `SET LOCAL` commands are intentionally inside the same transaction
    so they survive on pgbouncer in transaction mode and are scoped to
    exactly this request.

    The ``user_email`` (and derived domain) drive Postgres-level source-ACL
    filtering: episode/edge/entity RLS policies intersect those GUCs
    against ``episode_external_acl`` and only return rows the caller can
    see. See migration 20260521_0001 for the predicate.

    Pass ``bypass_external_acl=True`` for service callers (workers,
    agent tokens with kind='service', or privileged admin endpoints like
    the permissions inspector). The bypass GUC short-circuits the RLS
    predicate to TRUE; workspace RLS still applies.
    """
    sm = get_sessionmaker()
    async with sm() as session, session.begin():
        # Drop into the non-bypass app role for this transaction so RLS
        # policies actually enforce. The connecting superuser otherwise
        # bypasses every policy. Wrapped in best-effort: if the role
        # doesn't exist yet (pre-migration), fall back to the superuser
        # — admin DDL and migrations rely on this fallback.
        from sqlalchemy import text as _text
        try:
            await session.execute(_text("SET LOCAL ROLE memory_app"))
        except Exception:
            pass  # role not yet created
        if workspace_id is not None:
            await session.execute(
                _sql_set_local("app.current_workspace_id", workspace_id)
            )
        if user_id is not None:
            await session.execute(
                _sql_set_local("app.current_user_id", user_id)
            )
        if user_email:
            email = user_email.strip().lower()
            await session.execute(
                _sql_set_local("app.current_user_email", email)
            )
            if "@" in email:
                await session.execute(
                    _sql_set_local(
                        "app.current_user_domain", email.split("@", 1)[1]
                    )
                )
        if bypass_external_acl:
            await session.execute(
                _sql_set_local("app.bypass_external_acl", "true")
            )
        yield session


_ALLOWED_RLS_KEYS = frozenset({
    "app.current_workspace_id",
    "app.current_user_id",
    "app.current_user_email",
    "app.current_user_domain",
    "app.bypass_external_acl",
})


def _sql_set_local(key: str, value: str):
    from sqlalchemy import text

    # `set_config(text, text, is_local)` takes the key as a parameter, so we
    # can bind it safely instead of f-stringing it into the SQL. The
    # whitelist assertion is belt-and-suspenders: if a future refactor
    # passes an arbitrary key, we fail fast rather than executing it.
    if key not in _ALLOWED_RLS_KEYS:
        raise ValueError(f"rejected unknown RLS key: {key!r}")
    return text("SELECT set_config(:k, :v, true)").bindparams(k=key, v=value)
