"""Agent-to-agent provenance (Phase O3).

When meta-agent B writes a fact derived from agent A's prior work,
``add_fact(..., derived_from_activity_ids=[A's activity id])`` records
a ``prov:wasDerivedFrom`` link between the two activities. The chain
is queryable via ``get_provenance`` and ``derivation_chain``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.api.mcp.tools import invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain import provenance as prov_mod


def _principal(user_id: str, workspace_id: str, *, kind: str = "service") -> Principal:
    return Principal(
        user_id=user_id, email="agent@x.com",
        workspace_id=workspace_id, role="editor",
        claims={"kind": "agent_token"}, kind=kind,
    )


@pytest.mark.asyncio
async def test_add_fact_records_derivation_link(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    principal = _principal(user_id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=user_id) as s:
        bob = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Bob A2A", embed=False,
        )

        # Agent A writes a primary fact.
        result_a = await invoke_tool(
            s, workspace_id=ws_id, actor_id=user_id,
            name="add_fact",
            arguments={
                "subject": two_people["alice"],
                "predicate": "knows",
                "object": bob.id,
                "fact": "Alice knows Bob",
            },
            principal=principal,
        )
        assert "error" not in result_a, result_a
        edge_a_id = result_a["edge"]["id"]
        a_activity_id = (
            await s.execute(
                text("SELECT prov_activity_id::text FROM edge WHERE id = :id"),
                {"id": edge_a_id},
            )
        ).scalar_one()

        # Meta-agent B writes a derived fact citing A's activity.
        result_b = await invoke_tool(
            s, workspace_id=ws_id, actor_id=user_id,
            name="add_fact",
            arguments={
                "subject": bob.id,
                "predicate": "knows",
                "object": two_people["alice"],
                "fact": "Bob knows Alice (derived from observation)",
                "derived_from_activity_ids": [a_activity_id],
            },
            principal=principal,
        )
        assert "error" not in result_b, result_b
        edge_b_id = result_b["edge"]["id"]
        b_activity_id = (
            await s.execute(
                text("SELECT prov_activity_id::text FROM edge WHERE id = :id"),
                {"id": edge_b_id},
            )
        ).scalar_one()

        # derivation_chain walks B → A.
        chain = await prov_mod.derivation_chain(s, b_activity_id)
        assert any(act.id == a_activity_id for act in chain), [
            act.id for act in chain
        ]

        # get_edge_provenance exposes the link in JSON-LD.
        doc = await prov_mod.get_edge_provenance(s, edge_b_id)
    assert doc is not None
    derived = doc.get("wasDerivedFrom")
    assert derived is not None
    nodes = derived if isinstance(derived, list) else [derived]
    activity_nodes = [n for n in nodes if n.get("@type") == "Activity"]
    assert any(
        n["@id"].endswith(a_activity_id) for n in activity_nodes
    ), nodes


@pytest.mark.asyncio
async def test_derivation_rejects_self_link(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as s:
        activity_id = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="manual_edit",
            agent_kind="user", agent_ref=user_id,
        )
        with pytest.raises(ValueError):
            await prov_mod.link_derivation(
                s, workspace_id=ws_id,
                derived_activity_id=activity_id,
                upstream_activity_id=activity_id,
            )
