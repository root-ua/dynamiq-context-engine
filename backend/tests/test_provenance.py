"""W3C PROV-O provenance — activity lifecycle + edge attribution."""
from __future__ import annotations

import pytest

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import provenance as prov


@pytest.mark.asyncio
async def test_activity_lifecycle(workspace):
    ws_id = workspace["workspace_id"]
    user_id = workspace["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        activity_id = await prov.start_activity(
            session,
            workspace_id=ws_id,
            kind="extraction",
            agent_kind="llm",
            agent_ref="claude-sonnet-4-6",
            agent_version="20260513",
            inputs={"episode_id": "abc"},
        )
        await prov.end_activity(
            session, activity_id, outputs={"created_edges": ["e1", "e2"]}
        )
        a = await prov.get_activity(session, activity_id)
    assert a is not None
    assert a.kind == "extraction"
    assert a.agent_kind == "llm"
    assert a.agent_ref == "claude-sonnet-4-6"
    assert a.inputs == {"episode_id": "abc"}
    assert a.outputs == {"created_edges": ["e1", "e2"]}
    assert a.ended_at is not None


@pytest.mark.asyncio
async def test_edge_carries_prov_activity_id(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        activity_id = await prov.start_activity(
            session,
            workspace_id=ws_id,
            kind="manual_edit",
            agent_kind="user",
            agent_ref=user_id,
        )
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            embed=False,
            run_contradictor=False,
            prov_activity_id=activity_id,
        )

        # The edge row should reference the activity. add_fact's returned
        # dataclass doesn't expose it yet (read-side ergonomics for later),
        # but get_edge_provenance pulls it via SQL.
        doc = await prov.get_edge_provenance(session, edge.id)

    assert doc is not None
    assert doc["@type"][0] == "Entity"
    assert doc["dce:fact"] == "Alice works at Acme"
    assert "wasGeneratedBy" in doc
    activity = doc["wasGeneratedBy"]
    assert activity["dce:kind"] == "manual_edit"
    assert activity["wasAssociatedWith"]["dce:agentKind"] == "user"


@pytest.mark.asyncio
async def test_prov_context_includes_prov_namespace(two_people):
    """JSON-LD @context must declare the W3C PROV-O namespace."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            embed=False,
            run_contradictor=False,
        )
        doc = await prov.get_edge_provenance(session, edge.id)

    assert doc is not None
    ctx = doc["@context"]
    assert ctx["prov"] == "http://www.w3.org/ns/prov#"
    assert ctx["wasGeneratedBy"]["@id"] == "prov:wasGeneratedBy"
    assert ctx["wasAttributedTo"]["@id"] == "prov:wasAttributedTo"
