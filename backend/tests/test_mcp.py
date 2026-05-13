"""MCP tool registry + behavioural tests."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.api.mcp.tools import TOOLS, TOOLS_BY_NAME, invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import provenance as prov_mod


def test_registry_contains_core_tools():
    required = {
        "search_memory", "get_entity", "graph_query",
        "add_fact", "invalidate_fact", "add_episode",
        "update_entity", "ontology_describe",
        "create_entity_type", "create_relation_type",
        "propose_ontology", "as_of_query",
    }
    assert required.issubset(TOOLS_BY_NAME.keys())
    assert len(TOOLS) == len(TOOLS_BY_NAME)


def test_every_tool_exposes_json_schema():
    for t in TOOLS:
        schema = t.input_schema.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


def _principal(user_id: str, workspace_id: str, *, kind: str = "user") -> Principal:
    return Principal(
        user_id=user_id,
        email="test@example.com",
        workspace_id=workspace_id,
        role="editor",
        claims={"kind": "agent_token" if kind == "service" else "session"},
        kind=kind,
    )


@pytest.mark.asyncio
async def test_mcp_add_fact_starts_prov_activity(two_people):
    """J2 — MCP-driven add_fact must attach a prov_activity row.

    Without this, agent-authored facts come back from get_provenance
    with ``wasGeneratedBy = None``, undermining the governance pitch.
    """
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    principal = _principal(user_id, ws_id, kind="service")

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        result = await invoke_tool(
            session,
            workspace_id=ws_id,
            actor_id=user_id,
            name="add_fact",
            arguments={
                "subject": two_people["alice"],
                "predicate": "works_at",
                "object": two_people["acme"],
                "fact": "Alice works at Acme",
            },
            principal=principal,
        )
        assert "error" not in result, result
        edge = result["edge"]

        row = (
            await session.execute(
                text(
                    "SELECT prov_activity_id::text FROM edge WHERE id = :id"
                ),
                {"id": edge["id"]},
            )
        ).first()
        assert row is not None
        assert row[0] is not None, "MCP add_fact did not attach prov_activity_id"

        doc = await prov_mod.get_edge_provenance(session, edge["id"])
    assert doc is not None
    assert doc.get("wasGeneratedBy") is not None
    activity = doc["wasGeneratedBy"]
    assert activity["dce:kind"] == "manual_edit"
    assert activity["wasAssociatedWith"]["dce:agentKind"] == "system"


@pytest.mark.asyncio
async def test_mcp_add_episode_starts_prov_activity(workspace):
    """Sister of the add_fact test: every agent-authored episode also
    needs a prov_activity row."""
    ws_id = workspace["workspace_id"]
    user_id = workspace["user_id"]
    principal = _principal(user_id, ws_id, kind="service")

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        result = await invoke_tool(
            session,
            workspace_id=ws_id,
            actor_id=user_id,
            name="add_episode",
            arguments={
                "content": "Alice joined Acme today.",
                "source_kind": "agent",
                "extract": False,
            },
            principal=principal,
        )
        assert "error" not in result, result
        ep_id = result["episode_id"]
        row = (
            await session.execute(
                text(
                    "SELECT prov_activity_id::text FROM episode WHERE id = :id"
                ),
                {"id": ep_id},
            )
        ).first()
    assert row is not None
    assert row[0] is not None, "MCP add_episode did not attach prov_activity_id"
