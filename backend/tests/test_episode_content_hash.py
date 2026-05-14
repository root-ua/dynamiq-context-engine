"""Episode content-hash dedup (Phase PP3)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import episode as episode_mod
from app.domain.workspace import create_workspace


@pytest.mark.asyncio
async def test_add_episode_dedupes_by_content_hash():
    """Submitting the same content twice into the same workspace
    returns the same episode id and marks the second as deduped."""
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'pp3')"
            ),
            {"id": owner_id, "e": f"pp3-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"pp3-{suffix}",
            name="PP3",
        )
    ws_id = ws.id

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        first = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Alice joined Acme on 2025-01-15.",
            source_kind="agent", embed=False,
        )
        second = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Alice joined Acme on 2025-01-15.",
            source_kind="agent", embed=False,
        )

    assert first.id == second.id, "same content should resolve to same id"
    assert first.deduped is False
    assert second.deduped is True


@pytest.mark.asyncio
async def test_add_episode_distinct_content_creates_separate_rows():
    """Different content lands two episodes (sanity check)."""
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'pp3b')"
            ),
            {"id": owner_id, "e": f"pp3b-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"pp3b-{suffix}",
            name="PP3b",
        )
    ws_id = ws.id

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        first = await episode_mod.add_episode(
            s, workspace_id=ws_id, content="Fact A.",
            source_kind="agent", embed=False,
        )
        second = await episode_mod.add_episode(
            s, workspace_id=ws_id, content="Fact B.",
            source_kind="agent", embed=False,
        )

    assert first.id != second.id
    assert first.deduped is False
    assert second.deduped is False
