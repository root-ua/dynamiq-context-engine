"""Fact review queue — threshold routing, approve, reject."""
from __future__ import annotations

import pytest

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import proposals as proposals_mod


@pytest.mark.asyncio
async def test_propose_above_threshold_writes_edge(two_people):
    """confidence=0.95 with default workspace threshold (0.7) goes straight to edge."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.95,
            created_by=user_id,
        )
    assert write.kind == "edge"
    assert write.edge is not None
    assert write.edge.confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_propose_in_band_enqueues_pending(two_people):
    """0.3 <= confidence < 0.7 lands in pending_fact for review."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.5,
            created_by=user_id,
        )
        assert write.kind == "pending"
        assert write.pending_fact_id is not None

        proposal = await proposals_mod.get_proposal(session, write.pending_fact_id)
    assert proposal is not None
    assert proposal.status == "pending"
    assert proposal.reason == "below_threshold"


@pytest.mark.asyncio
async def test_propose_below_floor_auto_rejects(two_people):
    """confidence < 0.3 lands as rejected for audit."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.15,
            created_by=user_id,
        )
        assert write.kind == "rejected"
        proposal = await proposals_mod.get_proposal(session, write.pending_fact_id)
    assert proposal is not None
    assert proposal.status == "rejected"
    assert proposal.reason == "auto_rejected_below_floor"


@pytest.mark.asyncio
async def test_approve_promotes_pending_to_edge(two_people):
    """approve_proposal materialises an edge that reuses cardinality rules."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.55,
            created_by=user_id,
        )
        assert write.pending_fact_id is not None

        edge = await proposals_mod.approve_proposal(
            session,
            proposal_id=write.pending_fact_id,
            principal_user_id=user_id,
            comment="Confirmed against Slack thread",
        )
        # Live truth: query the graph back.
        rows = await edge_mod.live_edges(
            session, subject_id=two_people["alice"], predicate="works_at"
        )
        proposal = await proposals_mod.get_proposal(session, write.pending_fact_id)

    assert edge.confidence == pytest.approx(0.55)
    assert any(r.id == edge.id for r in rows)
    assert proposal is not None
    assert proposal.status == "approved"
    assert proposal.approved_edge_id == edge.id


@pytest.mark.asyncio
async def test_reject_keeps_pending_as_audit(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.55,
            created_by=user_id,
        )
        rejected = await proposals_mod.reject_proposal(
            session,
            proposal_id=write.pending_fact_id,
            principal_user_id=user_id,
            reason="Misread date — facts are unrelated",
        )
        rows = await edge_mod.live_edges(
            session, subject_id=two_people["alice"], predicate="works_at"
        )
    assert rejected.status == "rejected"
    assert rejected.reason == "Misread date — facts are unrelated"
    assert rows == []  # nothing in the live graph


@pytest.mark.asyncio
async def test_custom_threshold_per_relation(workspace, two_people):
    """A relation-specific policy overrides the workspace default."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        # Find the works_at relation id for this workspace specifically.
        # RLS would normally narrow this, but explicit filtering keeps the
        # test deterministic across leftover rows from prior runs.
        from sqlalchemy import text

        rel = (
            await session.execute(
                text(
                    "SELECT id::text FROM relation_type "
                    "WHERE slug = 'works_at' AND workspace_id = :ws"
                ),
                {"ws": ws_id},
            )
        ).scalar_one()

        await proposals_mod.upsert_policy(
            session,
            workspace_id=ws_id,
            relation_type_id=rel,
            min_confidence=0.95,
            auto_reject_below=0.5,
        )

        # confidence=0.8 would pass the default 0.7 — but is below the
        # custom 0.95 threshold for works_at specifically.
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.8,
            created_by=user_id,
        )
    assert write.kind == "pending", "0.8 should be 'pending' under the 0.95 threshold"


@pytest.mark.asyncio
async def test_approve_rejects_orphaned_source_episode(two_people):
    """J4 — approving a pending fact whose source episode was deleted
    must fail loudly, not silently write a dangling edge.

    The customer-facing risk: an extraction job creates a pending fact
    citing episode E; an admin deletes E to clean up an ingest mistake;
    a reviewer later approves the fact without realising the citation
    is now broken. The resulting edge has source_id pointing to a
    non-existent row, and the provenance chain quietly breaks.
    """

    from sqlalchemy import text

    from app.db.session import session_scope
    from app.domain import edge as edge_mod
    from app.domain import episode as episode_mod
    from app.domain import proposals as proposals_mod

    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        ep = await episode_mod.add_episode(
            session,
            workspace_id=ws_id,
            content="Alice joined Acme.",
            source_kind="agent",
            embed=False,
        )
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.5,
            source_id=ep.id,
            source_kind="episode",
            created_by=user_id,
        )
        assert write.kind == "pending"
        proposal_id = write.pending_fact_id

        # Hard-delete the source episode (soft-delete would also count).
        await session.execute(
            text("DELETE FROM episode WHERE id = :id"), {"id": ep.id}
        )

        with pytest.raises(proposals_mod.ProposalError) as ei:
            await proposals_mod.approve_proposal(
                session,
                proposal_id=proposal_id,
                principal_user_id=user_id,
            )
    assert "source_episode_missing" in str(ei.value)
