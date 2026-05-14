"""Triage enrichment + bulk MCP (Phase QQ3).

``list_proposals`` returns enriched rows so the validator persona can
triage in one tool call: proposer kind, email, source episode
snippet, upstream activity ids, and the user who triggered ingestion.

``bulk_approve_proposals`` / ``bulk_reject_proposals`` MCP tools wrap
the per-proposal approve/reject so a validator agent doesn't have to
serialise N round-trips.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.api.mcp.tools import invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain import ontology as ontology_mod
from app.domain import proposals as proposals_mod
from app.domain import provenance as prov_mod
from app.domain.workspace import create_workspace


async def _setup() -> tuple[str, str, str, str, str]:
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'qq3')"
            ),
            {"id": owner_id, "e": f"qq3-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"qq3-{suffix}", name="QQ3",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        alice = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice E", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme E", embed=False,
        )
    return owner_id, ws_id, alice.id, acme.id, f"qq3-{suffix}@x.com"


async def _seed_pending(
    ws_id: str, owner_id: str, alice_id: str, acme_id: str,
    *, conf: float, fact: str, episode_text: str,
) -> tuple[str, str, str]:
    """Returns (pending_id, activity_id, episode_id)."""
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content=episode_text, source_kind="agent",
            created_by=owner_id, embed=False,
        )
        activity_id = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="extraction",
            agent_kind="llm", agent_ref="claude-sonnet-4-6",
        )
        relation = await ontology_mod.get_relation_type(s, "works_at")
        assert relation is not None
        pending_id = await proposals_mod.enqueue_pending_fact(
            s, workspace_id=ws_id,
            subject_id=alice_id, predicate_id=relation.id,
            object_id=acme_id, fact=fact,
            confidence=conf, reason="below_threshold",
            source_id=ep.id, source_kind="episode",
            prov_activity_id=activity_id, status="pending",
        )
    return pending_id, activity_id, ep.id


@pytest.mark.asyncio
async def test_list_proposals_returns_enriched_fields():
    owner_id, ws_id, alice_id, acme_id, _owner_email = await _setup()
    pending_id, _activity_id, _episode_id = await _seed_pending(
        ws_id, owner_id, alice_id, acme_id,
        conf=0.5, fact="Alice works at Acme",
        episode_text="Internal memo dated 2019: Alice joined Acme last year.",
    )

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        rows = await proposals_mod.list_proposals(
            s, workspace_id=ws_id, status="pending",
        )

    assert len(rows) == 1
    row = rows[0]
    assert row.id == pending_id
    assert row.proposer_kind == "llm"
    assert row.proposer_agent_ref == "claude-sonnet-4-6"
    # LLM doesn't have an app_user row — proposer_email should be None.
    assert row.proposer_email is None
    assert row.source_episode_snippet is not None
    assert "Alice joined Acme" in row.source_episode_snippet
    assert row.upstream_activity_ids == []
    assert row.triggered_by_user_id == owner_id


@pytest.mark.asyncio
async def test_list_proposals_walks_upstream_activity_chain():
    owner_id, ws_id, alice_id, acme_id, _ = await _setup()
    _pending_id, activity_id, _ = await _seed_pending(
        ws_id, owner_id, alice_id, acme_id,
        conf=0.5, fact="Alice works at Acme",
        episode_text="Doc.",
    )

    # Add an upstream activity (e.g. the activity that triggered the
    # extraction). list_proposals should surface it.
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        upstream = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="manual_edit",
            agent_kind="user", agent_ref=owner_id,
        )
        await prov_mod.link_derivation(
            s, workspace_id=ws_id,
            derived_activity_id=activity_id,
            upstream_activity_id=upstream,
            kind="derived",
        )

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        rows = await proposals_mod.list_proposals(
            s, workspace_id=ws_id, status="pending",
        )
    assert len(rows) == 1
    assert upstream in (rows[0].upstream_activity_ids or [])


@pytest.mark.asyncio
async def test_bulk_approve_promotes_all_proposals():
    owner_id, ws_id, alice_id, _acme_id, _ = await _setup()
    bob_ids: list[str] = []
    for i in range(3):
        # Vary the object so cardinality-one on works_at doesn't
        # close earlier ones. Need a fresh org per fact.
        async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
            org = await entity_mod.create(
                s, workspace_id=ws_id, type_ref="organization",
                canonical=f"Org-{i}", embed=False,
            )
        # works_at is high_stakes + cardinality_one — too constrained
        # for parallel approval. Use ``member_of`` which is multi-card.
        async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
            relation = await ontology_mod.get_relation_type(s, "member_of")
            assert relation is not None
            pid = await proposals_mod.enqueue_pending_fact(
                s, workspace_id=ws_id,
                subject_id=alice_id, predicate_id=relation.id,
                object_id=org.id, fact=f"Alice member_of Org-{i}",
                confidence=0.5, reason="below_threshold",
                status="pending",
            )
            bob_ids.append(pid)

    principal = Principal(
        user_id=owner_id, email="t@x.com",
        workspace_id=ws_id, role="editor",
        claims={}, kind="user",
    )
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=owner_id,
            name="bulk_approve_proposals",
            arguments={"ids": bob_ids, "comment": "validator: looks fine"},
            principal=principal,
        )
    assert result["approved_count"] == 3
    assert result["failed_count"] == 0
    assert all(r["ok"] for r in result["results"])
    assert all("approved_edge_id" in r for r in result["results"])


@pytest.mark.asyncio
async def test_bulk_reject_records_reason():
    owner_id, ws_id, alice_id, _acme_id, _ = await _setup()

    pending_ids: list[str] = []
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        relation = await ontology_mod.get_relation_type(s, "member_of")
        assert relation is not None
        for _ in range(2):
            org = await entity_mod.create(
                s, workspace_id=ws_id, type_ref="organization",
                canonical=f"OrgR-{uuid4().hex[:4]}", embed=False,
            )
            pid = await proposals_mod.enqueue_pending_fact(
                s, workspace_id=ws_id,
                subject_id=alice_id, predicate_id=relation.id,
                object_id=org.id, fact="Alice member_of OrgR",
                confidence=0.4, reason="below_threshold",
                status="pending",
            )
            pending_ids.append(pid)

    principal = Principal(
        user_id=owner_id, email="t@x.com",
        workspace_id=ws_id, role="editor",
        claims={}, kind="user",
    )
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=owner_id,
            name="bulk_reject_proposals",
            arguments={"ids": pending_ids, "reason": "validator: low quality"},
            principal=principal,
        )
    assert result["rejected_count"] == 2

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        for pid in pending_ids:
            p = await proposals_mod.get_proposal(s, pid)
            assert p is not None
            assert p.status == "rejected"
            assert p.reason == "validator: low quality"
