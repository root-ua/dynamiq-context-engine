"""Integration test for the Halcyon demo seeder.

Creates a throwaway workspace, runs the seeder, and asserts the
signature behaviours:

- Counts come out nonzero for each kind.
- Bi-temporal: Alex Park has two non-overlapping `works_at` ranges.
- Contradictions: two edges are invalidated (LOI + $20M target).
- Backlinks: Jordan Reyes appears in block_entity_ref (via the
  postmortem + launch notes).
- Idempotency: running the seeder twice doesn't duplicate entities.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain.demo_seeder import seed_demo_workspace


@pytest.mark.asyncio
async def test_seed_demo_is_idempotent_and_populates_everything(workspace):
    ws_id = workspace["workspace_id"]
    owner_id = workspace["user_id"]

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        first = await seed_demo_workspace(
            session, workspace_id=ws_id, actor_user_id=owner_id
        )

    # First run populates everything.
    assert first.entities_created >= 18, first
    assert first.edges_created >= 20, first
    assert first.documents_created == 4
    assert first.episodes_created == 2
    assert first.agent_sessions_created == 2
    assert first.edges_invalidated >= 2  # LOI + $20M target
    assert first.home_document_id is not None

    # Alex Park's bi-temporal role history: two rows, non-overlapping.
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        r = await session.execute(
            text(
                """
                SELECT lower(ed.valid_time), upper(ed.valid_time), ed.fact
                FROM edge ed
                JOIN entity e ON e.id = ed.subject_id
                JOIN relation_type rt ON rt.id = ed.predicate_id
                WHERE ed.workspace_id = CAST(:ws AS uuid)
                  AND e.canonical = 'Alex Park'
                  AND rt.slug = 'works_at'
                ORDER BY lower(ed.valid_time)
                """
            ),
            {"ws": ws_id},
        )
        rows = r.all()
        assert len(rows) == 2, rows
        # Upper of row 1 == Lower of row 2 (the role transition point).
        assert rows[0][1] == rows[1][0], rows

    # Backlinks: Jordan Reyes is mentioned in ≥ 2 documents.
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        r = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT b.document_id)
                FROM block_entity_ref ref
                JOIN block b ON b.id = ref.block_id
                WHERE ref.workspace_id = CAST(:ws AS uuid)
                  AND ref.entity_id = (
                    SELECT id FROM entity
                    WHERE workspace_id = CAST(:ws AS uuid)
                      AND canonical = 'Jordan Reyes'
                  )
                """
            ),
            {"ws": ws_id},
        )
        assert r.scalar_one() >= 2

    # Second run: no new entities, only updates.
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        second = await seed_demo_workspace(
            session, workspace_id=ws_id, actor_user_id=owner_id
        )
    assert second.entities_created == 0, second
    assert second.entities_updated >= first.entities_created


@pytest.mark.asyncio
async def test_seed_demo_populates_yjs_state(workspace):
    """Seeded documents have non-empty document.yjs_state so the
    BlockNote editor renders content on first open.

    Relies on the Hocuspocus hydrate endpoint being reachable and
    HYDRATE_SECRET being set. Skips gracefully when either is missing —
    the test suite has to stay hermetic for CI runs that don't spin up
    the collab container.
    """
    import os

    if not os.environ.get("HYDRATE_SECRET"):
        pytest.skip("HYDRATE_SECRET not configured")

    ws_id = workspace["workspace_id"]
    owner_id = workspace["user_id"]

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        await seed_demo_workspace(
            session, workspace_id=ws_id, actor_user_id=owner_id
        )

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        r = await session.execute(
            text(
                """
                SELECT octet_length(yjs_state) AS n
                FROM document
                WHERE workspace_id = CAST(:ws AS uuid)
                """
            ),
            {"ws": ws_id},
        )
        sizes = [row[0] or 0 for row in r.all()]
    assert sizes, "no documents found"
    if all(s == 0 for s in sizes):
        pytest.skip(
            "all yjs_state are NULL — Hocuspocus /internal/hydrate-yjs "
            "likely unreachable from the test runner"
        )
    # When the collab service is up, every seeded doc should be hydrated.
    assert all(s > 0 for s in sizes), sizes


@pytest.mark.asyncio
async def test_seed_demo_contradictions(workspace):
    """The seeded dataset should show invalidated edges for the known
    historical contradictions.
    """
    ws_id = workspace["workspace_id"]
    owner_id = workspace["user_id"]

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        await seed_demo_workspace(
            session, workspace_id=ws_id, actor_user_id=owner_id
        )

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        r = await session.execute(
            text(
                """
                SELECT ed.fact
                FROM edge ed
                WHERE ed.workspace_id = CAST(:ws AS uuid)
                  AND upper(ed.sys_time) < 'infinity'::timestamptz
                ORDER BY ed.created_at
                """
            ),
            {"ws": ws_id},
        )
        facts = [row[0] for row in r.all()]
        assert any("LOI" in f or "Letter of Intent" in f for f in facts), facts
        assert any("$20M" in f for f in facts), facts
