"""Advisory-lock concurrent-write correctness (Phase PP5).

Two parallel ``add_fact`` calls on the same (workspace, subject,
predicate) tuple must NOT both insert. The pg_advisory_xact_lock in
``edge.add_fact`` serializes them; the second call sees the first's
row and dedupes (returns the same id).

This is the bug the user reported as "10+ people simultaneously
posting → conflicting duplicate facts about the same subject".
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain.workspace import create_workspace


async def _setup_workspace_with_entities():
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'pp5')"
            ),
            {"id": owner_id, "e": f"pp5-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"pp5-{suffix}",
            name="PP5",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        a = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice C", embed=False,
        )
        b = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Bob C", embed=False,
        )
    return owner_id, ws_id, a.id, b.id


@pytest.mark.asyncio
async def test_concurrent_add_fact_does_not_double_insert():
    """Two parallel add_fact calls on the same triple end up with
    exactly one live edge — the advisory lock + dedup converge them.
    """
    owner_id, ws_id, alice_id, bob_id = await _setup_workspace_with_entities()

    async def writer():
        async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
            return await edge_mod.add_fact(
                s, workspace_id=ws_id,
                subject_id=alice_id, predicate="knows", object_id=bob_id,
                fact="Alice knows Bob",
                embed=False, run_contradictor=False,
            )

    results = await asyncio.gather(writer(), writer(), writer())
    ids = {r.id for r in results}
    # All three writers should converge on the same edge id.
    assert len(ids) == 1, f"expected one shared edge id, got {ids}"

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        live = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": alice_id, "o": bob_id},
            )
        ).scalar_one()
    assert live == 1
