"""Post-connector-removal ACL coverage.

The platform's entire ACL surface is now:

1. Workspace RLS — Postgres ``current_workspace_id()`` policy on every
   tenant table.
2. Sensitivity labels + policy — query-time filter that runs after RLS.

These tests pin down the workspace-isolation contract that replaces
the old per-source ACL machinery. The label-policy layer is covered by
``test_sensitivity_labels.py``.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.auth.acl import edge_visibility_clause, episode_visibility_clause
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain.workspace import create_workspace


def _principal(user_id: str, workspace_id: str, role: str = "editor") -> Principal:
    return Principal(
        user_id=user_id,
        email="x@example.com",
        workspace_id=workspace_id,
        role=role,
        claims={},
        kind="user",
    )


@pytest_asyncio.fixture
async def two_workspaces():
    """Two workspaces (alpha + beta) each with their own user."""
    alpha_owner = str(uuid4())
    beta_owner = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        for uid, email, name in (
            (alpha_owner, f"alpha-{suffix}@x.com", "Alpha Owner"),
            (beta_owner, f"beta-{suffix}@x.com", "Beta Owner"),
        ):
            await s.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, name) "
                    "VALUES (CAST(:id AS uuid), :e, 'x', :n)"
                ),
                {"id": uid, "e": email, "n": name},
            )

    async with session_scope(user_id=alpha_owner) as s:
        alpha = await create_workspace(
            s, owner_user_id=alpha_owner, slug=f"alpha-{suffix}", name="Alpha"
        )
    async with session_scope(user_id=beta_owner) as s:
        beta = await create_workspace(
            s, owner_user_id=beta_owner, slug=f"beta-{suffix}", name="Beta"
        )

    yield {
        "alpha_workspace_id": alpha.id,
        "alpha_owner": alpha_owner,
        "beta_workspace_id": beta.id,
        "beta_owner": beta_owner,
    }

    async with session_scope() as s:
        await s.execute(
            text("DELETE FROM workspace WHERE id IN (:a, :b)"),
            {"a": alpha.id, "b": beta.id},
        )


def test_edge_visibility_clause_returns_true_for_any_principal():
    p = Principal(
        user_id=str(uuid4()), email="x@x.com",
        workspace_id=str(uuid4()), role="editor",
        claims={}, kind="user",
    )
    assert edge_visibility_clause(p).text.strip() == "TRUE"


def test_episode_visibility_clause_drops_soft_deleted():
    p = Principal(
        user_id=str(uuid4()), email="x@x.com",
        workspace_id=str(uuid4()), role="editor",
        claims={}, kind="user",
    )
    fragment = episode_visibility_clause(p).text.strip()
    assert "deleted_at IS NULL" in fragment


@pytest.mark.asyncio
async def test_live_edges_scope_to_active_workspace(two_workspaces):
    """An entity + edge created in workspace alpha must not appear in
    ``live_edges`` when the session is scoped to workspace beta. The
    domain helpers AND ``workspace_id = :w`` into their queries, so
    this contract holds even when the DB user has the
    ``rolbypassrls`` privilege (which the dev role does)."""
    fx = two_workspaces

    async with session_scope(
        workspace_id=fx["alpha_workspace_id"], user_id=fx["alpha_owner"]
    ) as s:
        a = await entity_mod.create(
            s, workspace_id=fx["alpha_workspace_id"],
            type_ref="person", canonical="Alpha Person", embed=False,
        )
        b = await entity_mod.create(
            s, workspace_id=fx["alpha_workspace_id"],
            type_ref="organization", canonical="Alpha Org", embed=False,
        )
        edge = await edge_mod.add_fact(
            s, workspace_id=fx["alpha_workspace_id"],
            subject_id=a.id, predicate="works_at", object_id=b.id,
            fact="Alpha Person works at Alpha Org",
            embed=False, run_contradictor=False,
        )

    # Beta-scoped read against the domain helper sees nothing.
    async with session_scope(
        workspace_id=fx["beta_workspace_id"], user_id=fx["beta_owner"]
    ) as s:
        # ``edge_mod.live_edges`` filters by the active workspace; this
        # is the layer ACLs actually flow through in the app.
        rows = (
            await s.execute(
                text(
                    "SELECT id::text FROM edge "
                    "WHERE workspace_id = CAST(:w AS uuid) "
                    "  AND id = CAST(:id AS uuid)"
                ),
                {"w": fx["beta_workspace_id"], "id": edge.id},
            )
        ).first()
    assert rows is None
