"""Closed-edge retention purge (Phase QQ4).

``purge_closed_edges`` hard-deletes edges where
``upper(sys_time) < now() - retention_days``. Per-workspace setting
``edge_retention_days`` in ``workspace.settings``; ``0`` (default)
disables.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain.workspace import create_workspace
from app.workers.jobs import purge_closed_edges


async def _setup() -> tuple[str, str, str, str]:
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'qq4')"
            ),
            {"id": owner_id, "e": f"qq4-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"qq4-{suffix}", name="QQ4",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        bob = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Bob R", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme R", embed=False,
        )
    return owner_id, ws_id, bob.id, acme.id


async def _set_retention(ws_id: str, days: int) -> None:
    async with session_scope() as s:
        await s.execute(
            text(
                """
                UPDATE workspace
                SET settings = COALESCE(settings, '{}'::jsonb)
                  || CAST(:patch AS jsonb)
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": ws_id,
                "patch": json.dumps({"edge_retention_days": days}),
            },
        )


async def _back_date_edge_closure(edge_id: str, days_ago: int) -> None:
    """Rewrite an edge's ``sys_time`` to a fully-past range
    (``[now - N - 1d, now - Nd)``) so the retention cron picks it
    up. Tests need this because the cron uses wall-clock comparison."""
    async with session_scope() as s:
        await s.execute(
            text(
                """
                UPDATE edge
                SET sys_time = tstzrange(
                    now() - ((CAST(:days AS int) + 1) || ' days')::interval,
                    now() - (CAST(:days AS int) || ' days')::interval,
                    '[)'
                )
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": edge_id, "days": days_ago},
        )


@pytest.mark.asyncio
async def test_purge_deletes_edges_past_retention():
    owner_id, ws_id, bob_id, acme_id = await _setup()
    await _set_retention(ws_id, days=7)

    edge_ids: list[str] = []
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        for i in range(5):
            edge = await edge_mod.add_fact(
                s, workspace_id=ws_id,
                subject_id=bob_id, predicate="member_of", object_id=acme_id,
                fact=f"endorsement {i}",
                embed=False, run_contradictor=False,
                # Force-distinct rows by writing then immediately closing.
                dedup=False,
            )
            edge_ids.append(edge.id)
            await edge_mod.invalidate(
                s, edge_id=edge.id, reason="testing",
            )

    # Back-date each edge's closure to 8 days ago (past 7-day retention).
    for eid in edge_ids:
        await _back_date_edge_closure(eid, days_ago=8)

    result = await purge_closed_edges({})
    assert result["purged"] >= 5, result

    async with session_scope() as s:
        remaining = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": edge_ids},
            )
        ).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_purge_skips_workspaces_with_retention_zero():
    owner_id, ws_id, bob_id, acme_id = await _setup()
    # No retention set — default 0 = disabled.

    edge_ids: list[str] = []
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        edge = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False, dedup=False,
        )
        await edge_mod.invalidate(s, edge_id=edge.id, reason="testing")
        edge_ids.append(edge.id)

    await _back_date_edge_closure(edge_ids[0], days_ago=365)

    await purge_closed_edges({})

    async with session_scope() as s:
        survives = (
            await s.execute(
                text("SELECT COUNT(*) FROM edge WHERE id = CAST(:id AS uuid)"),
                {"id": edge_ids[0]},
            )
        ).scalar_one()
    assert survives == 1


@pytest.mark.asyncio
async def test_purge_preserves_live_edges():
    """Live edges (``upper(sys_time) = 'infinity'``) are never touched
    even if they're old."""
    owner_id, ws_id, bob_id, acme_id = await _setup()
    await _set_retention(ws_id, days=1)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        edge = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False, dedup=False,
        )

    await purge_closed_edges({})

    async with session_scope() as s:
        survives = (
            await s.execute(
                text("SELECT COUNT(*) FROM edge WHERE id = CAST(:id AS uuid)"),
                {"id": edge.id},
            )
        ).scalar_one()
    assert survives == 1


@pytest.mark.asyncio
async def test_purge_preserves_audit_log_and_activity():
    """Even though the edge row goes, its prov_activity + audit_log
    rows survive — provenance is durable across retention."""
    owner_id, ws_id, bob_id, acme_id = await _setup()
    await _set_retention(ws_id, days=7)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        edge = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=bob_id, predicate="member_of", object_id=acme_id,
            embed=False, run_contradictor=False, dedup=False,
        )
        edge_id = edge.id
        # Capture the activity id before deletion.
        act_id = (
            await s.execute(
                text(
                    "SELECT prov_activity_id::text FROM edge "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": edge_id},
            )
        ).scalar()
        await edge_mod.invalidate(s, edge_id=edge_id, reason="for-purge")

    await _back_date_edge_closure(edge_id, days_ago=8)
    await purge_closed_edges({})

    async with session_scope() as s:
        edge_gone = (
            await s.execute(
                text("SELECT COUNT(*) FROM edge WHERE id = CAST(:id AS uuid)"),
                {"id": edge_id},
            )
        ).scalar_one()
        if act_id:
            act_kept = (
                await s.execute(
                    text(
                        "SELECT COUNT(*) FROM prov_activity "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": act_id},
                )
            ).scalar_one()
            assert act_kept == 1
        audit_kept = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM audit_log "
                    "WHERE target_id = CAST(:id AS uuid) "
                    "  AND action = 'edge.invalidate'"
                ),
                {"id": edge_id},
            )
        ).scalar_one()
    assert edge_gone == 0
    assert audit_kept >= 1
