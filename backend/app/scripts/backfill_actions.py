"""Backfill the built-in action types for every existing workspace.

The Phase D migration only registered actions on new workspaces (via
``create_workspace`` calling ``ensure_builtin_actions``). Workspaces that
existed before the migration need a one-off pass.

Run from inside the backend container::

    python -m app.scripts.backfill_actions

Idempotent — re-running is safe; ``ensure_builtin_actions`` uses
``ON CONFLICT (workspace_id, slug) DO UPDATE``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.domain.action import ensure_builtin_actions

log = get_logger(__name__)


async def main() -> None:
    configure_logging("INFO")

    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id::text FROM workspace "
                    "WHERE deleted_at IS NULL ORDER BY created_at"
                )
            )
        ).all()
    workspace_ids = [r[0] for r in rows]
    log.info("backfill_actions.start", count=len(workspace_ids))

    seeded = 0
    for ws_id in workspace_ids:
        async with session_scope(workspace_id=ws_id) as session:
            try:
                await ensure_builtin_actions(session, workspace_id=ws_id)
                seeded += 1
            except Exception as exc:
                log.warning(
                    "backfill_actions.failed", workspace_id=ws_id, error=str(exc)
                )

    log.info("backfill_actions.done", seeded=seeded, total=len(workspace_ids))


if __name__ == "__main__":
    asyncio.run(main())
