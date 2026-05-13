"""J1 — `merge_entities` must invoke the cluster safeguard.

The safeguard exists in ``entity_resolver.cluster_is_safe_to_merge`` but
was orphaned: nothing in ``entity.merge_entities`` ever called it.
That meant an agent could merge a 100-entity LLM-driven cluster of
low-confidence guesses without any human-in-the-loop check, silently
collapsing facts that should have stayed separate.

These tests pin the safeguard to its caller. Cluster size 2 (the
default merge_entities shape) is always safe; cluster size > 10 with
weak edges must refuse.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod


@pytest.mark.asyncio
async def test_two_entity_merge_is_safe(two_people):
    """The legacy pair-merge call shape must continue to work."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        survivor = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice S", aliases=["Alice Smith"], embed=False,
        )
        loser = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice Smyth", embed=False,
        )
        merged = await entity_mod.merge_entities(
            session, survivor_id=survivor.id, loser_id=loser.id
        )
    assert merged.id == survivor.id


@pytest.mark.asyncio
async def test_large_cluster_with_weak_edges_refuses(two_people):
    """12 entities all linked by 0.5-confidence edges → must refuse.

    Construct a cluster: alice + 11 'Alice-ish' duplicates, each linked
    by a low-confidence edge to acme. Then attempt a pair merge that
    pulls all 12 into one — the safeguard should fire on the *cluster*
    (the set of entities touched by the merge).
    """
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        cluster_entities = []
        survivor = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice (canonical)", embed=False,
        )
        cluster_entities.append(survivor.id)
        for i in range(11):
            dupe = await entity_mod.create(
                session, workspace_id=ws_id, type_ref="person",
                canonical=f"Alice (variant {i})", embed=False,
            )
            cluster_entities.append(dupe.id)
            # Connect every duplicate to Acme with a low-confidence edge.
            await edge_mod.add_fact(
                session,
                workspace_id=ws_id,
                subject_id=dupe.id,
                predicate="works_at",
                object_id=two_people["acme"],
                fact=f"Alice variant {i} works at Acme",
                confidence=0.5,
                embed=False,
                run_contradictor=False,
            )

        with pytest.raises(entity_mod.EntityMergeUnsafeError):
            await entity_mod.merge_cluster(
                session,
                survivor_id=survivor.id,
                loser_ids=cluster_entities[1:],
                actor_id=user_id,
            )

        # Confirm no rewrites happened — every duplicate still has its
        # own edge to Acme.
        kept = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM entity
                    WHERE id = ANY(:ids) AND merged_into_id IS NULL
                    """
                ),
                {"ids": cluster_entities},
            )
        ).scalar_one()
    assert kept == 12, "no entity should have been merged"


@pytest.mark.asyncio
async def test_large_cluster_with_strong_edges_succeeds(two_people):
    """Same shape but every edge is 0.95-confidence — safe to merge."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        survivor = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice strong", embed=False,
        )
        loser_ids: list[str] = []
        for i in range(11):
            dupe = await entity_mod.create(
                session, workspace_id=ws_id, type_ref="person",
                canonical=f"Alice strong variant {i}", embed=False,
            )
            loser_ids.append(dupe.id)
            await edge_mod.add_fact(
                session,
                workspace_id=ws_id,
                subject_id=dupe.id,
                predicate="works_at",
                object_id=two_people["acme"],
                fact=f"Alice strong variant {i} works at Acme",
                confidence=0.95,
                embed=False,
                run_contradictor=False,
            )

        result = await entity_mod.merge_cluster(
            session,
            survivor_id=survivor.id,
            loser_ids=loser_ids,
            actor_id=user_id,
        )
    assert result.id == survivor.id


@pytest.mark.asyncio
async def test_small_cluster_bypasses_safeguard(two_people):
    """A 3-entity cluster with weak edges should still merge — the
    safeguard only kicks in over the 10-entity threshold."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        survivor = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice small", embed=False,
        )
        loser_ids: list[str] = []
        for i in range(2):
            dupe = await entity_mod.create(
                session, workspace_id=ws_id, type_ref="person",
                canonical=f"Alice small {i}", embed=False,
            )
            loser_ids.append(dupe.id)
            await edge_mod.add_fact(
                session,
                workspace_id=ws_id,
                subject_id=dupe.id,
                predicate="works_at",
                object_id=two_people["acme"],
                fact=f"Alice small {i} works at Acme",
                confidence=0.5,
                embed=False,
                run_contradictor=False,
            )
        result = await entity_mod.merge_cluster(
            session,
            survivor_id=survivor.id,
            loser_ids=loser_ids,
            actor_id=user_id,
        )
    assert result.id == survivor.id
