"""Audit-log writer.

Every workspace-scoped state change should land here. Reads happen via
``app.api.rest.audit``.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def write(
    session: AsyncSession,
    *,
    workspace_id: str,
    actor_kind: str,
    actor_id: str | None,
    action: str,
    target_kind: str,
    target_id: str | None,
    diff: dict[str, Any] | None = None,
) -> None:
    """Insert one row into audit_log."""
    if actor_kind not in ("user", "agent", "system"):
        raise ValueError(f"invalid actor_kind: {actor_kind!r}")
    await session.execute(
        text(
            """
            INSERT INTO audit_log
              (workspace_id, actor_kind, actor_id, action,
               target_kind, target_id, diff)
            VALUES (
              CAST(:ws AS uuid), :ak, CAST(:aid AS uuid), :action,
              :tk, CAST(:tid AS uuid), CAST(:diff AS jsonb)
            )
            """
        ),
        {
            "ws": workspace_id,
            "ak": actor_kind,
            "aid": actor_id,
            "action": action,
            "tk": target_kind,
            "tid": target_id,
            "diff": json.dumps(diff) if diff is not None else None,
        },
    )
