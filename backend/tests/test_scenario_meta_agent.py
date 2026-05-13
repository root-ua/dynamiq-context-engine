"""Q2 — Meta-agent persona.

Agent A writes a primary fact via MCP. Meta-agent B reads A's activity
and writes a derived fact citing it. The chain is queryable via
``get_provenance`` and ``derivation_chain``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.api.mcp.tools import invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain import provenance as prov_mod


pytestmark = pytest.mark.scenario


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user_id=user_id, email="agent@x.com",
        workspace_id=workspace_id, role="editor",
        claims={"kind": "agent_token"}, kind="service",
    )


@pytest.mark.asyncio
async def test_meta_agent_chain(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme Q2", embed=False,
        )
        eu = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="topic",
            canonical="EU expansion", embed=False,
        )
        risk = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="topic",
            canonical="High compliance risk", embed=False,
        )

        # Agent A writes the primary fact (Acme expanded to EU).
        result_a = await invoke_tool(
            s, workspace_id=ws_id, actor_id=e.alice.id,
            name="add_fact",
            arguments={
                "subject": acme.id, "predicate": "tagged", "object": eu.id,
                "fact": "Acme is expanding into the EU",
            },
            principal=principal,
        )
        assert "error" not in result_a, result_a
        edge_a_id = result_a["edge"]["id"]
        activity_a_id = (
            await s.execute(
                text("SELECT prov_activity_id::text FROM edge WHERE id = :id"),
                {"id": edge_a_id},
            )
        ).scalar_one()

        # Meta-agent B reads A's trace (it's in agent_tool_call now)
        # and derives a new fact citing A's activity.
        result_b = await invoke_tool(
            s, workspace_id=ws_id, actor_id=e.alice.id,
            name="add_fact",
            arguments={
                "subject": acme.id, "predicate": "tagged", "object": risk.id,
                "fact": "Acme's EU expansion implies high compliance risk",
                "derived_from_activity_ids": [activity_a_id],
            },
            principal=principal,
        )
        assert "error" not in result_b, result_b
        edge_b_id = result_b["edge"]["id"]
        activity_b_id = (
            await s.execute(
                text("SELECT prov_activity_id::text FROM edge WHERE id = :id"),
                {"id": edge_b_id},
            )
        ).scalar_one()

        # derivation_chain walks B → A.
        chain = await prov_mod.derivation_chain(s, activity_b_id)
        assert any(act.id == activity_a_id for act in chain)

        # get_fact on B's fact also surfaces the upstream chain via
        # the wasDerivedFrom in the response.
        fact_b = await invoke_tool(
            s, workspace_id=ws_id, actor_id=e.alice.id,
            name="get_fact",
            arguments={"subject": acme.id, "predicate": "tagged",
                       "object": risk.id},
            principal=principal,
        )
    assert "error" not in fact_b
    derived = fact_b.get("wasDerivedFrom")
    assert derived is not None
    nodes = derived if isinstance(derived, list) else [derived]
    activity_ids = [
        n["@id"] for n in nodes if n.get("@type") == "Activity"
    ]
    assert any(activity_a_id in i for i in activity_ids), activity_ids
