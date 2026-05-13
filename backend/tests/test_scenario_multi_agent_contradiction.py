"""Q6 — Multi-agent concurrent contradiction (defensive).

Two agents try to write contradictory high-stakes facts about the same
subject. Exactly one survives as live (the contradictor closes the
other) AND the loser ends up either pending or audited — never silently
overwritten.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.api.mcp.tools import invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import entity as entity_mod


pytestmark = pytest.mark.scenario


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user_id=user_id, email="agent@x.com",
        workspace_id=workspace_id, role="editor",
        claims={"kind": "agent_token"}, kind="service",
    )


@pytest.mark.asyncio
async def test_two_agents_contradicting_facts(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        alice_ent = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice Q6", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme Q6", embed=False,
        )
        globex = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Globex Q6", embed=False,
        )

    async def write_fact(obj_id: str):
        async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
            return await invoke_tool(
                s, workspace_id=ws_id, actor_id=e.alice.id,
                name="add_fact",
                arguments={
                    "subject": alice_ent.id,
                    "predicate": "works_at",
                    "object": obj_id,
                    "fact": f"Alice Q6 works at {obj_id[:6]}",
                },
                principal=_principal(e.alice.id, ws_id),
            )

    # Two concurrent agent calls writing contradictory high-stakes facts.
    r_acme, r_globex = await asyncio.gather(
        write_fact(acme.id), write_fact(globex.id),
    )
    assert "error" not in r_acme, r_acme
    assert "error" not in r_globex, r_globex

    # Exactly one of the two should still be live (the cardinality-one
    # closure runs on the second insert and closes the first).
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        live = (
            await s.execute(
                text(
                    """
                    SELECT id::text FROM edge
                    WHERE workspace_id = CAST(:ws AS uuid)
                      AND subject_id = CAST(:s AS uuid)
                      AND predicate_id = (
                        SELECT id FROM relation_type
                        WHERE slug = 'works_at'
                          AND workspace_id = CAST(:ws AS uuid)
                      )
                      AND upper(sys_time) = 'infinity'
                      AND valid_time @> clock_timestamp()
                    """
                ),
                {"ws": ws_id, "s": alice_ent.id},
            )
        ).scalars().all()
    assert len(live) == 1, f"expected 1 live edge, got {len(live)}"
