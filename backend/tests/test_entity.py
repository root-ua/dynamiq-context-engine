"""Entity CRUD + alias resolution + merge."""
from __future__ import annotations

import pytest

from app.db.session import session_scope
from app.domain import entity as entity_mod


@pytest.mark.asyncio
async def test_create_and_fetch_by_ref(workspace):
    ws_id = workspace["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=workspace["user_id"]) as session:
        created = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Zoe Diaz", aliases=["Z.D."], embed=False,
        )

        by_id = await entity_mod.get(session, created.id)
        by_iri = await entity_mod.get(session, created.iri)
        by_name = await entity_mod.get(session, "zoe diaz")
    assert by_id is not None and by_id.id == created.id
    assert by_iri is not None and by_iri.id == created.id
    assert by_name is not None and by_name.id == created.id


@pytest.mark.asyncio
async def test_resolve_by_alias_prefers_exact_match(workspace):
    ws_id = workspace["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=workspace["user_id"]) as session:
        await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Avery Parker", aliases=["ap", "Parker"], embed=False,
        )
        hits = await entity_mod.resolve_by_alias(
            session, workspace_id=ws_id, name="Avery Parker", type_ref="person",
        )
    assert hits, "should return at least the created entity"
    assert hits[0].canonical == "Avery Parker"


@pytest.mark.asyncio
async def test_merge_rewrites_edges_and_marks_loser(two_people):
    ws_id = two_people["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=two_people["user_id"]) as session:
        # Create a duplicate Alice.
        dup = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice Smith", aliases=["Alice"], embed=False,
        )
        # Add a fact on the duplicate.
        from app.domain import edge as edge_mod

        await edge_mod.add_fact(
            session, workspace_id=ws_id,
            subject_id=dup.id, predicate="works_at",
            object_id=two_people["acme"], embed=False, run_contradictor=False,
        )
        survivor = await entity_mod.merge_entities(
            session, survivor_id=two_people["alice"], loser_id=dup.id,
            actor_kind="user", actor_id=two_people["user_id"],
        )
        # Loser should redirect via merged_into_id.
        fetched_loser = await entity_mod.get(session, dup.id)
    assert survivor.id == two_people["alice"]
    # Following merge, a get(loser_id) resolves to the survivor.
    assert fetched_loser is not None and fetched_loser.id == survivor.id
