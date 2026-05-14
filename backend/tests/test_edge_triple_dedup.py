"""Exact-triple edge dedup + invalidate-closes-dupes (Phase PP2)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain.workspace import create_workspace


async def _setup_pair(slug_prefix: str):
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', :n)"
            ),
            {"id": owner_id, "e": f"{slug_prefix}-{suffix}@x.com", "n": slug_prefix},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"{slug_prefix}-{suffix}",
            name=slug_prefix,
        )
    return owner_id, ws.id


@pytest.mark.asyncio
async def test_add_fact_dedupes_exact_triple():
    """Calling add_fact twice with the same (subj, pred, obj) returns
    the same edge id; only one live edge exists."""
    owner_id, ws_id = await _setup_pair("pp2a")

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        a = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice DD", embed=False,
        )
        b = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Bob DD", embed=False,
        )
        first = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="knows", object_id=b.id,
            fact="Alice knows Bob", embed=False, run_contradictor=False,
        )
        second = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="knows", object_id=b.id,
            fact="Alice knows Bob", embed=False, run_contradictor=False,
        )
        live_rows = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE workspace_id = CAST(:w AS uuid) "
                    "  AND subject_id = CAST(:s AS uuid) "
                    "  AND predicate_id = (SELECT predicate_id FROM edge WHERE id = CAST(:eid AS uuid)) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"w": ws_id, "s": a.id, "o": b.id, "eid": first.id},
            )
        ).scalar_one()

    assert first.id == second.id
    assert live_rows == 1


@pytest.mark.asyncio
async def test_add_fact_dedup_can_be_disabled():
    """Explicit dedup=False creates a fresh row (rare opt-out)."""
    owner_id, ws_id = await _setup_pair("pp2b")

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        a = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice ND", embed=False,
        )
        b = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme ND", embed=False,
        )
        first = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="member_of", object_id=b.id,
            fact="Alice member_of Acme", embed=False, run_contradictor=False,
        )
        # Same triple with dedup=False should produce a different id.
        # But the partial unique index would reject this if both share
        # the same lower(valid_time). Test with a distinct valid_from.
        from datetime import UTC, datetime

        second = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="member_of", object_id=b.id,
            fact="Alice member_of Acme", embed=False, run_contradictor=False,
            valid_from=datetime(2099, 1, 1, tzinfo=UTC),
            dedup=False,
        )
    assert first.id != second.id


@pytest.mark.asyncio
async def test_invalidate_closes_duplicate_live_edges():
    """Manually inserting two live duplicates then invalidating one
    should close the other(s) too."""
    owner_id, ws_id = await _setup_pair("pp2c")

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        a = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice IV", embed=False,
        )
        b = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme IV", embed=False,
        )
        first = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="member_of", object_id=b.id,
            fact="Alice member_of Acme IV", embed=False, run_contradictor=False,
        )
        # Force a second live duplicate with a distinct valid_from so it
        # slips past the partial unique index.
        from datetime import UTC, datetime

        dup = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="member_of", object_id=b.id,
            fact="Alice member_of Acme IV (dup)",
            valid_from=datetime(2099, 6, 1, tzinfo=UTC),
            embed=False, run_contradictor=False, dedup=False,
        )

        # Both live before invalidate.
        live_before = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": a.id, "o": b.id},
            )
        ).scalar_one()
        assert live_before == 2

        await edge_mod.invalidate(s, edge_id=first.id, reason="testing")

        live_after = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:s AS uuid) "
                    "  AND object_id = CAST(:o AS uuid) "
                    "  AND upper(sys_time) = 'infinity'"
                ),
                {"s": a.id, "o": b.id},
            )
        ).scalar_one()
    assert live_after == 0, "invalidating one should close all triple duplicates"
    # Sanity: the duplicate's id wasn't lost — both should now have
    # upper(sys_time) != infinity.
    _ = dup.id
