"""Multi-agent consensus on dedup (Phase QQ2).

When agent B asserts a fact agent A already wrote, ``add_fact`` returns
A's existing edge (PP2 dedup). QQ2 also:

- Links B's activity to A's via ``prov_activity_derivation`` (kind
  ``quoted``).
- Writes an ``audit_log`` row with ``action='edge.endorsed'`` so the
  triage queue can show "N agents endorsed this".
- Surfaces ``dce:endorsementCount`` on the JSON-LD provenance bundle.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import provenance as prov_mod
from app.domain.workspace import create_workspace


async def _setup() -> tuple[str, str, str, str]:
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'qq2')"
            ),
            {"id": owner_id, "e": f"qq2-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"qq2-{suffix}", name="QQ2",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        bob = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Bob C", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme C", embed=False,
        )
    return owner_id, ws_id, bob.id, acme.id


@pytest.mark.asyncio
async def test_dedup_links_second_agents_provenance():
    owner_id, ws_id, bob_id, acme_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # Agent A's activity.
        act_a = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="extraction",
            agent_kind="llm", agent_ref="agent-a",
        )
        edge_a = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            fact="Bob member_of Acme",
            embed=False, run_contradictor=False,
            prov_activity_id=act_a, created_by=owner_id,
        )

        # Agent B's activity, asserting the same fact.
        act_b = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="extraction",
            agent_kind="llm", agent_ref="agent-b",
        )
        edge_b = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            fact="Bob member_of Acme",
            embed=False, run_contradictor=False,
            prov_activity_id=act_b, created_by=owner_id,
        )

    # Same edge returned.
    assert edge_a.id == edge_b.id

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # Derivation row: B quoted A.
        deriv = (
            await s.execute(
                text(
                    """
                    SELECT derivation_kind FROM prov_activity_derivation
                    WHERE derived_activity_id = CAST(:b AS uuid)
                      AND upstream_activity_id = CAST(:a AS uuid)
                    """
                ),
                {"a": act_a, "b": act_b},
            )
        ).mappings().first()
    assert deriv is not None
    assert deriv["derivation_kind"] == "quoted"

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        audit = (
            await s.execute(
                text(
                    """
                    SELECT diff FROM audit_log
                    WHERE action = 'edge.endorsed'
                      AND target_id = CAST(:edge AS uuid)
                    """
                ),
                {"edge": edge_a.id},
            )
        ).mappings().first()
    assert audit is not None
    assert audit["diff"]["endorsing_activity"] == act_b
    assert audit["diff"]["original_activity"] == act_a

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        doc = await prov_mod.get_edge_provenance(s, edge_a.id)
    assert doc is not None
    assert doc["dce:endorsementCount"] == 2  # A + B


@pytest.mark.asyncio
async def test_dedup_without_prov_activity_id_is_silent():
    """If the second caller didn't supply a prov_activity_id, we
    can't record an endorsement — but dedup still works and we don't
    crash."""
    owner_id, ws_id, bob_id, acme_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        act_a = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="extraction",
            agent_kind="llm", agent_ref="agent-a",
        )
        edge_a = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False,
            prov_activity_id=act_a, created_by=owner_id,
        )
        # Second caller, no activity id.
        edge_b = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False,
            prov_activity_id=None, created_by=owner_id,
        )
    assert edge_a.id == edge_b.id

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # No derivation row created.
        deriv = (
            await s.execute(
                text(
                    """
                    SELECT COUNT(*) FROM prov_activity_derivation
                    WHERE upstream_activity_id = CAST(:a AS uuid)
                    """
                ),
                {"a": act_a},
            )
        ).scalar_one()
    assert deriv == 0


@pytest.mark.asyncio
async def test_same_agent_writing_twice_does_not_self_endorse():
    """A single agent re-asserting their own fact shouldn't generate
    a self-link or inflate endorsement_count."""
    owner_id, ws_id, bob_id, acme_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        act = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="extraction",
            agent_kind="llm", agent_ref="agent-a",
        )
        edge_a = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False,
            prov_activity_id=act, created_by=owner_id,
        )
        edge_b = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False,
            prov_activity_id=act, created_by=owner_id,  # same activity
        )
    assert edge_a.id == edge_b.id

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        doc = await prov_mod.get_edge_provenance(s, edge_a.id)
    assert doc is not None
    assert doc["dce:endorsementCount"] == 1
