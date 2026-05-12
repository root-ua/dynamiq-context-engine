"""Bi-temporal edge invariants.

These are the non-negotiable core guarantees of the memory platform.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.session import session_scope
from app.domain import edge as edge_mod


@pytest.mark.asyncio
async def test_add_fact_creates_live_edge(two_people):
    ws_id = two_people["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=two_people["user_id"]) as session:
        edge = await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"], fact="Alice works at Acme",
            embed=False, run_contradictor=False,
        )
    assert edge.sys_to is None
    assert edge.valid_to is None
    assert edge.predicate_slug == "works_at"


@pytest.mark.asyncio
async def test_invalidate_closes_both_axes(two_people):
    ws_id = two_people["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=two_people["user_id"]) as session:
        created = await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"], fact="Alice works at Acme",
            embed=False, run_contradictor=False,
        )

        at = datetime.now(UTC) + timedelta(minutes=1)
        closed = await edge_mod.invalidate(
            session, edge_id=created.id, invalidated_at=at, reason="left Acme"
        )
    assert closed.sys_to is not None, "sys_time should be closed"
    assert closed.valid_to is not None, "valid_time should be closed"


@pytest.mark.asyncio
async def test_as_of_sees_prior_truth(two_people):
    ws_id = two_people["workspace_id"]
    t1 = datetime(2025, 1, 1, tzinfo=UTC)
    async with session_scope(workspace_id=ws_id, user_id=two_people["user_id"]) as session:
        edge = await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"], fact="Alice works at Acme",
            valid_from=t1, embed=False, run_contradictor=False,
        )

        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        await edge_mod.invalidate(session, edge_id=edge.id, invalidated_at=t2)

        # At t1 + 1 day, Alice's 'works_at' should still resolve.
        historical = datetime(2025, 1, 2, tzinfo=UTC)
        rows = await edge_mod.as_of(
            session, valid_at=historical, subject_id=two_people["alice"],
            predicate="works_at",
        )
    assert rows, "as_of should return the edge that was live on 2025-01-02"


@pytest.mark.asyncio
async def test_cardinality_one_closes_overlapping_edge(two_people):
    """`works_at` has cardinality_object=one — adding a new one closes the old."""
    ws_id = two_people["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=two_people["user_id"]) as session:
        # Create a second organization.
        from app.domain import entity as entity_mod

        globex = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Globex", embed=False,
        )

        first = await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"], fact="Alice works at Acme",
            embed=False, run_contradictor=False,
        )
        assert first.sys_to is None

        await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=globex.id, fact="Alice works at Globex",
            embed=False, run_contradictor=False,
        )

        reread = await edge_mod.get(session, first.id)
    assert reread is not None
    assert reread.sys_to is not None, "cardinality_object=one should have closed the first edge"
