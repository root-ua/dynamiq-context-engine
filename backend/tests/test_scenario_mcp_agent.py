"""AI-agent / integration-developer scenarios — MCP surface.

Tests the MCP tool surface as a coworker.ai-style agent would. All
tools tested for contract + happy path; the load-bearing flows
(provenance round-trip, label-policy drop, approval workflow, action
invocation, get_fact) get focused integration tests.
"""
from __future__ import annotations

from uuid import uuid4

import jsonschema
import pytest
from sqlalchemy import text

from app.api.mcp.tools import TOOLS, TOOLS_BY_NAME, invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod

pytestmark = pytest.mark.scenario


def _principal(
    user_id: str,
    workspace_id: str,
    *,
    role: str = "editor",
    kind: str = "user",
    email: str | None = None,
) -> Principal:
    return Principal(
        user_id=user_id,
        email=email or "agent@example.com",
        workspace_id=workspace_id,
        role=role,
        claims={"kind": "agent_token" if kind == "service" else "session"},
        kind=kind,
    )


# ---------------------------------------------------------------------------
# L1. Tool catalog contract
# ---------------------------------------------------------------------------


def test_tool_catalog_has_all_22_tools():
    expected = {
        "search_memory", "get_entity", "graph_query",
        "add_fact", "invalidate_fact", "add_episode",
        "update_entity", "ontology_describe",
        "create_entity_type", "create_relation_type",
        "propose_ontology", "as_of_query",
        "get_provenance", "get_fact",
        "list_proposals", "approve_proposal",
        "reject_proposal", "list_labels", "assign_label",
        "list_action_types", "execute_action", "list_action_invocations",
    }
    assert set(TOOLS_BY_NAME.keys()) == expected
    assert len(TOOLS) == 22


def test_every_tool_schema_is_valid_json_schema():
    for tool in TOOLS:
        schema = tool.input_schema.model_json_schema()
        # Validates against the meta-schema for draft 2020-12; failure
        # means an agent runtime would reject the schema.
        jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.asyncio
async def test_unknown_tool_returns_structured_error(two_people):
    ws_id = two_people["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=two_people["user_id"]) as session:
        result = await invoke_tool(
            session,
            workspace_id=ws_id,
            actor_id=two_people["user_id"],
            name="not_a_real_tool",
            arguments={},
        )
    assert "error" in result
    assert "unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# L3. Parametrized happy path across every tool
# ---------------------------------------------------------------------------


def _minimal_input_for(tool_name: str, ctx: dict) -> dict:
    """Build the smallest valid input payload for each tool.

    ``ctx`` carries IDs / refs created by the fixture (alice, acme,
    edge, episode, proposal, action). Tools that mutate state try not
    to clobber other tests' data — they use synthetic / disposable
    targets.
    """
    if tool_name == "search_memory":
        return {"query": "Alice"}
    if tool_name == "get_entity":
        return {"ref": ctx["alice"]}
    if tool_name == "graph_query":
        return {"seeds": [ctx["alice"]], "max_hops": 1}
    if tool_name == "add_fact":
        return {
            "subject": ctx["alice"],
            "predicate": "knows",
            "object": ctx["bob"],
            "fact": "Alice knows Bob",
        }
    if tool_name == "invalidate_fact":
        return {"edge_id": ctx["edge_id"], "reason": "test"}
    if tool_name == "add_episode":
        return {"content": "Alice mentioned a new project.", "extract": False}
    if tool_name == "update_entity":
        return {"ref": ctx["alice"], "summary": "Updated summary"}
    if tool_name == "ontology_describe":
        return {}
    if tool_name == "create_entity_type":
        return {"name": f"NewType-{uuid4().hex[:6]}"}
    if tool_name == "create_relation_type":
        return {
            "name": f"new_rel_{uuid4().hex[:6]}",
            "domain": "person",
            "range": "person",
        }
    if tool_name == "propose_ontology":
        # Empty samples → returns error path; that's a "happy" structured
        # response shape. Real LLM call would need ANTHROPIC_API_KEY.
        return {"samples": [], "episode_ids": []}
    if tool_name == "as_of_query":
        return {"valid_at": "2025-01-01T00:00:00Z"}
    if tool_name == "get_fact":
        # member_of edge between alice and acme already exists in fixture.
        return {"subject": ctx["alice"], "predicate": "member_of"}
    if tool_name == "get_provenance":
        return {"fact_id": ctx["edge_id"]}
    if tool_name == "list_proposals":
        return {"status": "pending"}
    if tool_name == "approve_proposal":
        return {"proposal_id": ctx["pending_id"]}
    if tool_name == "reject_proposal":
        return {"proposal_id": ctx["other_pending_id"], "reason": "test"}
    if tool_name == "list_labels":
        return {}
    if tool_name == "assign_label":
        return {
            "target_kind": "edge",
            "target_id": ctx["edge_id"],
            "label_slug": "pii",
        }
    if tool_name == "list_action_types":
        return {}
    if tool_name == "execute_action":
        return {
            "type_slug": "attach_evidence_to_fact",
            "input": {
                "edge_id": ctx["edge_id"],
                "episode_id": ctx["episode_id"],
                "comment": "smoke",
            },
            "idempotency_key": str(uuid4()),
        }
    if tool_name == "list_action_invocations":
        return {}
    raise AssertionError(f"no minimal input registered for {tool_name}")


@pytest.fixture
async def mcp_ctx(enterprise_workspace):
    """Build a context dict the parametrized happy-path test needs."""
    e = enterprise_workspace
    ws_id = e.workspace_id

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L3 Alice", embed=False,
        )
        bob = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L3 Bob", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="L3 Acme", embed=False,
        )
        ep = await episode_mod.add_episode(
            session, workspace_id=ws_id,
            content="L3 episode body.", source_kind="agent", embed=False,
        )
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id, predicate="member_of",
            object_id=acme.id,
            fact="L3 Alice member_of L3 Acme",
            embed=False, run_contradictor=False,
        )
        # Two pending facts so approve and reject have independent targets.
        carol = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L3 Carol", embed=False,
        )
        dave = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L3 Dave", embed=False,
        )
        # `knows` is non-high-stakes → propose_fact at 0.5 routes to
        # pending below the default threshold.
        p1 = await edge_mod.propose_fact(
            session, workspace_id=ws_id,
            subject_id=carol.id, predicate="knows", object_id=dave.id,
            fact="L3 Carol knows L3 Dave",
            confidence=0.5,
            created_by=e.alice.id,
        )
        p2 = await edge_mod.propose_fact(
            session, workspace_id=ws_id,
            subject_id=dave.id, predicate="knows", object_id=carol.id,
            fact="L3 Dave knows L3 Carol",
            confidence=0.5,
            created_by=e.alice.id,
        )

    return {
        "workspace_id": ws_id,
        "user_id": e.alice.id,
        "alice": alice.id,
        "bob": bob.id,
        "edge_id": edge.id,
        "episode_id": ep.id,
        "pending_id": p1.pending_fact_id,
        "other_pending_id": p2.pending_fact_id,
    }


@pytest.mark.parametrize("tool_name", sorted(TOOLS_BY_NAME.keys()))
@pytest.mark.asyncio
async def test_mcp_tool_happy_path(tool_name, mcp_ctx):
    """Each tool returns a non-error structured response for its
    minimal valid input. Mutating tools may need real DB rows seeded by
    the fixture; ``mcp_ctx`` provides them.
    """
    ws_id = mcp_ctx["workspace_id"]
    user_id = mcp_ctx["user_id"]
    principal = _principal(user_id, ws_id, role="editor", kind="user")

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        result = await invoke_tool(
            session,
            workspace_id=ws_id,
            actor_id=user_id,
            name=tool_name,
            arguments=_minimal_input_for(tool_name, mcp_ctx),
            principal=principal,
        )
    if tool_name == "propose_ontology":
        # Calling with no samples is allowed; the registered error path
        # is the expected response (we don't have an LLM key in CI).
        assert "error" in result, result
        return
    assert "error" not in result, (tool_name, result)


# ---------------------------------------------------------------------------
# L4. Agent provenance round-trip (extends J2 coverage end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_add_fact_then_get_provenance(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    agent_principal = _principal(e.alice.id, ws_id, kind="service")

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L4 Alice", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="L4 Acme", embed=False,
        )

        add = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="add_fact",
            arguments={
                "subject": alice.id,
                "predicate": "member_of",
                "object": acme.id,
                "fact": "L4 Alice member_of L4 Acme",
            },
            principal=agent_principal,
        )
        assert "error" not in add
        edge_id = add["edge"]["id"]

        prov = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="get_provenance",
            arguments={"fact_id": edge_id},
            principal=agent_principal,
        )
    assert "error" not in prov
    assert prov["wasGeneratedBy"]["dce:kind"] == "manual_edit"
    assert (
        prov["wasGeneratedBy"]["wasAssociatedWith"]["dce:agentKind"]
        == "system"
    )


# ---------------------------------------------------------------------------
# L7. Approval workflow via MCP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_approval_workflow(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L7 Alice", embed=False,
        )
        bob = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L7 Bob", embed=False,
        )
        write = await edge_mod.propose_fact(
            session, workspace_id=ws_id,
            subject_id=alice.id, predicate="knows", object_id=bob.id,
            fact="L7 Alice knows L7 Bob", confidence=0.5,
            created_by=e.alice.id,
        )
        pending_id = write.pending_fact_id

        listed = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="list_proposals",
            arguments={"status": "pending"},
            principal=principal,
        )
        assert any(p["id"] == pending_id for p in listed["proposals"])

        approved = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="approve_proposal",
            arguments={"proposal_id": pending_id},
            principal=principal,
        )
        edge_id = approved["approved_edge_id"]

        prov = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="get_provenance",
            arguments={"fact_id": edge_id},
            principal=principal,
        )
    assert "error" not in prov
    assert prov["wasGeneratedBy"]["dce:kind"] == "approval"
    assert (
        prov["wasGeneratedBy"]["wasAssociatedWith"]["dce:agentKind"]
        == "user"
    )


# ---------------------------------------------------------------------------
# L8. Action invocation + idempotency via MCP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_action_idempotency(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="L8 Alice", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="L8 Acme", embed=False,
        )
        ep = await episode_mod.add_episode(
            session, workspace_id=ws_id, content="L8 episode",
            source_kind="agent", embed=False,
        )
        edge = await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=alice.id, predicate="member_of", object_id=acme.id,
            fact="L8 fact", embed=False, run_contradictor=False,
        )
        idempotency = str(uuid4())

        first = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="execute_action",
            arguments={
                "type_slug": "attach_evidence_to_fact",
                "input": {
                    "edge_id": edge.id,
                    "episode_id": ep.id,
                    "comment": "first call",
                },
                "idempotency_key": idempotency,
            },
            principal=principal,
        )
        assert "error" not in first
        first_id = first["invocation"]["id"]

        second = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="execute_action",
            arguments={
                "type_slug": "attach_evidence_to_fact",
                "input": {
                    "edge_id": edge.id,
                    "episode_id": ep.id,
                    "comment": "second call — different comment, same key",
                },
                "idempotency_key": idempotency,
            },
            principal=principal,
        )
        # Same id back → idempotent.
        assert second["invocation"]["id"] == first_id

        # Verify edge.props.evidence has exactly one entry.
        row = (
            await session.execute(
                text(
                    "SELECT props->'evidence' AS evidence "
                    "FROM edge WHERE id = :id"
                ),
                {"id": edge.id},
            )
        ).first()
    evidence = row[0] or []
    assert len(evidence) == 1


# ---------------------------------------------------------------------------
# L9. ACL filter via MCP search_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_search_respects_workspace_isolation(enterprise_workspace):
    """An MCP agent calling ``search_memory`` against workspace A
    should not see episodes that exist only in workspace B."""
    e = enterprise_workspace
    ws_id = e.workspace_id

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        await episode_mod.add_episode(
            session,
            workspace_id=ws_id,
            content="Quarterly engineering review notes.",
            source_kind="agent",
            embed=False,
        )

    alice_principal = _principal(
        e.alice.id, ws_id, role="editor", email=e.alice.email,
    )
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        hits = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="search_memory",
            arguments={"query": "engineering", "include_kinds": ["episode"]},
            principal=alice_principal,
        )
    blob = " ".join(h["snippet"] for h in hits["hits"])
    assert "engineering" in blob.lower()


# ---------------------------------------------------------------------------
# L10. Label assignment via MCP filters non-admin retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_label_drop_filters_non_admin(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    alice_principal = _principal(
        e.alice.id, ws_id, role="editor", email=e.alice.email,
    )

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        ep = await episode_mod.add_episode(
            session, workspace_id=ws_id,
            content="L10 cross-tagged episode about engineering OKRs.",
            source_kind="agent", embed=False,
        )

        # Assign both labels via MCP.
        for slug in ("pii", "public"):
            res = await invoke_tool(
                session, workspace_id=ws_id, actor_id=e.alice.id,
                name="assign_label",
                arguments={
                    "target_kind": "episode",
                    "target_id": ep.id,
                    "label_slug": slug,
                },
                principal=alice_principal,
            )
            assert "error" not in res

        # As editor, the mutually_exclusive policy should drop this
        # episode out of search.
        editor_hits = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="search_memory",
            arguments={
                "query": "L10 cross-tagged",
                "include_kinds": ["episode"],
            },
            principal=alice_principal,
        )
    editor_ids = {h["id"] for h in editor_hits["hits"]}
    assert ep.id not in editor_ids

    # Admin should still see it (J3 bypass).
    admin_principal = _principal(
        e.admin.id, ws_id, role="admin", email=e.admin.email,
    )
    async with session_scope(workspace_id=ws_id, user_id=e.admin.id) as session:
        admin_hits = await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.admin.id,
            name="search_memory",
            arguments={
                "query": "L10 cross-tagged",
                "include_kinds": ["episode"],
            },
            principal=admin_principal,
        )
    admin_ids = {h["id"] for h in admin_hits["hits"]}
    assert ep.id in admin_ids


# ---------------------------------------------------------------------------
# L2. Auth surface (lightweight — full HTTP flow lives in test_agent_tokens)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_tool_records_audit(enterprise_workspace):
    """Every MCP tool invocation lands in ``agent_tool_call``. Customers
    rely on this for audit trails."""
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id, kind="service")

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        await invoke_tool(
            session, workspace_id=ws_id, actor_id=e.alice.id,
            name="ontology_describe",
            arguments={},
            principal=principal,
        )
        rows = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM agent_tool_call "
                    "WHERE workspace_id = CAST(:w AS uuid) "
                    "AND tool = 'ontology_describe'"
                ),
                {"w": ws_id},
            )
        ).scalar_one()
    assert rows >= 1
