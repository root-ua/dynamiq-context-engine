"""Negation extraction closes live edges (Phase PP1).

Two layers of coverage:

* ``invalidate_matching_live`` — the helper the pipeline calls. Unit
  test verifies it closes every live triple that matches.
* Pipeline integration — stub the LLM so it emits an ``is_negation``
  edge; assert the pipeline routes it through the helper and the
  live edge is closed.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain.workspace import create_workspace


async def _setup() -> tuple[str, str, str, str]:
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'pp1')"
            ),
            {"id": owner_id, "e": f"pp1-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"pp1-{suffix}",
            name="PP1",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        bob = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Bob N", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme N", embed=False,
        )
    return owner_id, ws_id, bob.id, acme.id


@pytest.mark.asyncio
async def test_invalidate_matching_live_closes_specific_triple():
    """Calling the helper with (subj, pred, obj) closes the matching
    live edge and leaves unrelated edges untouched."""
    owner_id, ws_id, bob_id, acme_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # Seed: Bob works_at Acme (live).
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="works_at", object_id=acme_id,
            fact="Bob works at Acme", embed=False, run_contradictor=False,
        )
        # Seed unrelated: Bob knows another person — should survive.
        other = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Carol N", embed=False,
        )
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="knows", object_id=other.id,
            fact="Bob knows Carol", embed=False, run_contradictor=False,
        )

        closed = await edge_mod.invalidate_matching_live(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="works_at", object_id=acme_id,
            reason="testing-negation",
        )

    assert len(closed) == 1

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # works_at Acme closed.
        works_at_live = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": bob_id, "o": acme_id},
            )
        ).scalar_one()
        # knows still live (different object).
        knows_live = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id <> CAST(:acme AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": bob_id, "acme": acme_id},
            )
        ).scalar_one()

    assert works_at_live == 0
    assert knows_live == 1


@pytest.mark.asyncio
async def test_invalidate_matching_live_without_object_closes_all():
    """When ``object_id`` is omitted, every live edge with this
    (subject, predicate) is closed — semantics for 'Bob isn't
    working anywhere any more'."""
    owner_id, ws_id, bob_id, acme_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="works_at", object_id=acme_id,
            fact="Bob works at Acme", embed=False, run_contradictor=False,
        )

        closed = await edge_mod.invalidate_matching_live(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="works_at",
            object_id=None,
            reason="bob-quit",
        )

    assert len(closed) == 1


@pytest.mark.asyncio
async def test_pipeline_routes_negation_to_invalidate(monkeypatch):
    """Stub the LLM to emit an ``is_negation`` edge from an episode
    saying 'Bob no longer works at Acme'. Assert the pipeline closes
    the live edge and records it in ``invalidated_edges``."""
    owner_id, ws_id, bob_id, acme_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="works_at", object_id=acme_id,
            fact="Bob works at Acme", embed=False, run_contradictor=False,
        )
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Bob no longer works at Acme.",
            source_kind="agent", embed=False,
        )

    # Patch the LLM to emit a negation edge that matches the seeded
    # live fact. We re-use the existing ``Bob N`` and ``Acme N``
    # canonical names so the resolver Tier-1 picks them up.
    from app.extraction import pipeline as pipeline_mod
    from app.extraction.pipeline import Extraction, ExtractedEdge, ExtractedEntity

    async def fake_run_llm(*, snapshot: Any, text_: str) -> Extraction:
        return Extraction(
            entities=[
                ExtractedEntity(local_id="bob", name="Bob N", type_slug="person"),
                ExtractedEntity(local_id="acme", name="Acme N", type_slug="organization"),
            ],
            edges=[
                ExtractedEdge(
                    subject_local_id="bob",
                    predicate_slug="works_at",
                    object_local_id="acme",
                    fact="Bob no longer works at Acme",
                    is_negation=True,
                )
            ],
        )

    monkeypatch.setattr(pipeline_mod, "_run_llm", fake_run_llm)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        result = await pipeline_mod.process_episode(
            s, episode_id=ep.id, actor_id=owner_id,
        )

    assert result.errors == [], result.errors
    assert len(result.invalidated_edges) == 1
    assert result.created_edges == []

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        live = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": bob_id, "o": acme_id},
            )
        ).scalar_one()
    assert live == 0
