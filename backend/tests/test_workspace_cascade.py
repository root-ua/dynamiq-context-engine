"""Workspace deletion cascade.

Deleting a workspace must cascade through every tenant-scoped table.
This test seeds rows across the major tables and asserts the count
drops to zero after the delete.

If you add a new workspace-scoped table, add it to ``WS_TABLES``.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain import provenance as prov_mod
from app.domain import sensitivity as sens_mod
from app.domain.workspace import create_workspace

# Tables that should be empty for the deleted workspace's id after the
# cascade. Each entry is (table, workspace_id_column).
WS_TABLES: list[tuple[str, str]] = [
    ("entity", "workspace_id"),
    ("edge", "workspace_id"),
    ("episode", "workspace_id"),
    ("sensitivity_label", "workspace_id"),
    ("label_policy", "workspace_id"),
    ("episode_label", "workspace_id"),
    ("edge_label", "workspace_id"),
    ("action_type", "workspace_id"),
    ("action_invocation", "workspace_id"),
    ("prov_activity", "workspace_id"),
    ("prov_activity_derivation", "workspace_id"),
    ("audit_log", "workspace_id"),
    ("workspace_member", "workspace_id"),
    ("pending_fact", "workspace_id"),
]


@pytest.mark.asyncio
async def test_workspace_delete_cascades_to_all_tenant_tables():
    """Seed one row in each table; delete the workspace; assert zero."""
    owner_id = str(uuid4())
    email = f"casc-{uuid4().hex[:8]}@x.com"
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'cascade')"
            ),
            {"id": owner_id, "e": email},
        )

    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"casc-{uuid4().hex[:8]}",
            name="Cascade",
        )
    ws_id = ws.id

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        a = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical=f"Cascade Person {uuid4().hex[:6]}", embed=False,
        )
        b = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical=f"Cascade Org {uuid4().hex[:6]}", embed=False,
        )
        edge = await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=a.id, predicate="works_at", object_id=b.id,
            fact="Cascade Person works at Cascade Org",
            embed=False, run_contradictor=False,
        )
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id, content="cascade",
            source_kind="agent", embed=False,
        )
        label = await sens_mod.create_label(
            s, workspace_id=ws_id, slug="cascade-label", name="Cascade",
        )
        await sens_mod.assign_label(
            s, workspace_id=ws_id, target_kind="edge",
            target_id=edge.id, label_slug=label.slug,
        )
        await sens_mod.assign_label(
            s, workspace_id=ws_id, target_kind="episode",
            target_id=ep.id, label_slug=label.slug,
        )
        await sens_mod.create_policy(
            s, workspace_id=ws_id, name="cascade-policy",
            rule={"kind": "any_of", "labels": ["cascade-label"]},
            action="warn",
        )
        activity_id = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="manual_edit",
            agent_kind="user", agent_ref=owner_id,
        )
        upstream_id = await prov_mod.start_activity(
            s, workspace_id=ws_id, kind="extraction",
            agent_kind="llm", agent_ref="test",
        )
        await prov_mod.link_derivation(
            s, workspace_id=ws_id,
            derived_activity_id=activity_id,
            upstream_activity_id=upstream_id,
        )

    # Delete the workspace.
    async with session_scope() as s:
        await s.execute(
            text("DELETE FROM workspace WHERE id = CAST(:id AS uuid)"),
            {"id": ws_id},
        )

    # Verify every workspace-scoped table is empty for this workspace.
    async with session_scope() as s:
        for table, col in WS_TABLES:
            count = (
                await s.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table} "
                        f"WHERE {col} = CAST(:w AS uuid)"
                    ),
                    {"w": ws_id},
                )
            ).scalar_one()
            assert count == 0, (
                f"{table}.{col} still has {count} row(s) for the "
                f"deleted workspace — cascade is missing or table "
                f"isn't workspace-scoped"
            )
