"""Confidence-aware contradictor routing (Phase PP4)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import ontology as ontology_mod
from app.domain.workspace import create_workspace


async def _ensure_non_high_stakes_card_one(session, workspace_id: str) -> str:
    """Create (idempotent) a non-high-stakes cardinality-one relation
    we can use to exercise the confidence-aware contradictor branch.
    The seeded ontology only ships high_stakes cardinality-one
    relations, so PP4's middle branches aren't reachable on its own.
    """
    slug = "located_at_cc"
    existing = await ontology_mod.get_relation_type(session, slug)
    if existing:
        return existing.id
    rel = await ontology_mod.create_relation_type(
        session,
        workspace_id=workspace_id,
        name="Located At (test)",
        slug=slug,
        domain="organization",
        range_="organization",
        cardinality_subject="many",
        cardinality_object="one",
        temporal=True,
        high_stakes=False,
    )
    return rel.id


async def _setup() -> tuple[str, str, str, str, str]:
    """Returns (owner_id, ws_id, acme_id, sf_id, nyc_id) — exercises
    the new non-high-stakes cardinality-one relation ``located_at_cc``.
    """
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'pp4')"
            ),
            {"id": owner_id, "e": f"pp4-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"pp4-{suffix}",
            name="PP4",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        await _ensure_non_high_stakes_card_one(s, ws_id)
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme CC", embed=False,
        )
        sf = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="SF HQ", embed=False,
        )
        nyc = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="NYC HQ", embed=False,
        )
    return owner_id, ws_id, acme.id, sf.id, nyc.id


@pytest.mark.asyncio
async def test_lower_confidence_new_fact_routes_to_pending():
    """Existing live edge with conf 0.9; a contradicting new fact
    with conf 0.5 must NOT close the existing — it goes to pending."""
    owner_id, ws_id, acme_id, sf_id, nyc_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # Seed: Alice works_at Acme with confidence 0.9.
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=acme_id, predicate="located_at_cc", object_id=sf_id,
            fact="Acme located at SF", confidence=0.9,
            embed=False, run_contradictor=False,
        )
        # Contradicting low-conf write.
        result = await edge_mod.propose_fact(
            s, workspace_id=ws_id,
            subject_id=acme_id, predicate="located_at_cc", object_id=nyc_id,
            fact="Acme located at NYC", confidence=0.5,
        )

    assert result.kind == "pending"

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # Existing edge stays live.
        existing_live = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": acme_id, "o": sf_id},
            )
        ).scalar_one()
    assert existing_live == 1


@pytest.mark.asyncio
async def test_higher_confidence_new_fact_replaces_existing():
    """Existing edge with conf 0.5; contradicting new fact with conf
    0.95 should fall through to add_fact and close the existing."""
    owner_id, ws_id, acme_id, sf_id, nyc_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=acme_id, predicate="located_at_cc", object_id=sf_id,
            fact="Acme located at SF", confidence=0.5,
            embed=False, run_contradictor=False,
        )
        result = await edge_mod.propose_fact(
            s, workspace_id=ws_id,
            subject_id=acme_id, predicate="located_at_cc", object_id=nyc_id,
            fact="Acme located at NYC", confidence=0.95,
        )

    assert result.kind == "edge"

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        # Old Acme edge closed; new Globex edge live.
        live_objects = (
            await s.execute(
                text(
                    "SELECT object_id::text FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": acme_id},
            )
        ).scalars().all()
    assert set(live_objects) == {nyc_id}


@pytest.mark.asyncio
async def test_ambiguous_confidence_routes_to_pending():
    """Existing conf 0.8, new conf 0.85 (< 0.8 + 0.1) — ambiguous,
    route to pending."""
    owner_id, ws_id, acme_id, sf_id, nyc_id = await _setup()

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=acme_id, predicate="located_at_cc", object_id=sf_id,
            fact="Acme located at SF", confidence=0.8,
            embed=False, run_contradictor=False,
        )
        result = await edge_mod.propose_fact(
            s, workspace_id=ws_id,
            subject_id=acme_id, predicate="located_at_cc", object_id=nyc_id,
            fact="Acme located at NYC", confidence=0.85,
        )

    assert result.kind == "pending"
    # Existing stays.
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        live = (
            await s.execute(
                text(
                    "SELECT object_id::text FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": acme_id},
            )
        ).scalars().all()
    assert live == [sf_id]
