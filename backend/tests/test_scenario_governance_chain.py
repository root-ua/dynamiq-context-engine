"""Q4 — Governance chain.

Stresses the cross-feature stack: label assignment → policy drop →
admin bypass → high-sensitivity source recheck (now extended to graph
traversal in Phase P4).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.auth.jwt import Principal
from app.connectors import _drive_mock
from app.connectors.upsert import upsert_item
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import sensitivity as sens_mod
from app.retrieval.graph import traverse


pytestmark = pytest.mark.scenario


def _principal(user, ws_id, *, role: str | None = None) -> Principal:
    return Principal(
        user_id=user.id, email=user.email,
        workspace_id=ws_id, role=role or user.role,
        claims={}, kind="user",
    )


@pytest.mark.asyncio
async def test_high_sensitivity_recheck_in_graph_traverse(
    enterprise_workspace, monkeypatch,
):
    """An editor traversing a graph in a high-sensitivity workspace
    must NOT see edges whose Drive sources have been revoked.
    """
    e = enterprise_workspace
    ws_id = e.workspace_id

    # Seed a Drive-sourced edge first.
    async with session_scope(workspace_id=ws_id, user_id=e.owner.id) as s:
        for item in _drive_mock.initial_items():
            await upsert_item(
                s,
                workspace_id=ws_id,
                connector_instance_id=e.drive_instance_id,
                item=item,
            )
        ep_id = (
            await s.execute(
                text(
                    "SELECT id::text FROM episode "
                    "WHERE external_id = 'alpha-shared' "
                    "AND deleted_at IS NULL"
                )
            )
        ).scalar_one()
        alice_ent = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice Q4", embed=False,
        )
        eng = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Engineering Q4", embed=False,
        )
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=alice_ent.id, predicate="works_at", object_id=eng.id,
            fact="Alice Q4 works at Engineering Q4",
            source_id=ep_id, source_kind="episode",
            embed=False, run_contradictor=False,
        )
        await s.execute(
            text("UPDATE workspace SET high_sensitivity = TRUE WHERE id = :id"),
            {"id": ws_id},
        )

    from app.connectors import google_drive

    async def deny(self, session, *, workspace_id, principal_user_id, source_ref):
        return False

    monkeypatch.setattr(
        google_drive.GoogleDriveConnector, "check_access", deny, raising=True
    )

    # Editor traverses from alice → engineering. The edge is Drive-sourced
    # and the connector now denies access; the edge should be filtered
    # out.
    alice_principal = _principal(e.alice, ws_id)
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        sub = await traverse(
            s, workspace_id=ws_id, seeds=[alice_ent.id], max_hops=1,
            direction="both", principal=alice_principal,
        )
    drive_edges = [
        edge for edge in sub.edges
        if edge.subject_id == alice_ent.id and edge.object_id == eng.id
    ]
    assert drive_edges == []


@pytest.mark.asyncio
async def test_label_drop_for_editor_bypass_for_admin(enterprise_workspace):
    """Phase J3 + P5: label policy filters editor results, admin sees
    the same fact unfiltered."""
    e = enterprise_workspace
    ws_id = e.workspace_id

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        from app.domain import episode as episode_mod
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Cross-tagged episode about governance Q4.",
            source_kind="agent", embed=False,
        )
        for slug in ("pii", "public"):
            await sens_mod.assign_label(
                s, workspace_id=ws_id, target_kind="episode",
                target_id=ep.id, label_slug=slug,
            )
        editor_kept, summary = await sens_mod.apply_label_policy(
            s, workspace_id=ws_id,
            candidates=[{"kind": "episode", "id": ep.id}],
            principal=_principal(e.alice, ws_id),
        )
        admin_kept, _ = await sens_mod.apply_label_policy(
            s, workspace_id=ws_id,
            candidates=[{"kind": "episode", "id": ep.id}],
            principal=_principal(e.admin, ws_id, role="admin"),
        )
    assert editor_kept == []
    assert summary["dropped"] == 1
    assert len(admin_kept) == 1
