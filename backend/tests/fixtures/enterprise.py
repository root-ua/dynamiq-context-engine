"""Enterprise-persona scenario fixture.

Pre-seeded workspace shaped like a small enterprise customer:
- 3 users at different roles (admin / editor / editor)
- Built-in action types seeded
- ``pii`` and ``public`` sensitivity labels + a ``mutually_exclusive``
  drop policy ready to demo the governance pitch

After the Phase R connector removal there are no Drive / Notion
connector instances and no ``user_external_identity`` bridges — agents
push episodes / facts directly via the MCP surface, so external-system
ACLs are the agent's concern, not the platform's.

Used by ``test_scenario_*.py``. Each test gets a fresh fixture
(function scope) so seeds don't bleed between tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import sensitivity as sens_mod
from app.domain.action import ensure_builtin_actions
from app.domain.workspace import create_workspace


@dataclass
class EnterpriseUser:
    id: str
    email: str
    role: str  # 'admin' | 'editor' | 'viewer' | 'owner'


@dataclass
class EnterpriseFixture:
    workspace_id: str
    slug: str
    owner: EnterpriseUser
    admin: EnterpriseUser
    alice: EnterpriseUser
    carol: EnterpriseUser
    labels: dict[str, str]  # slug → id


@pytest_asyncio.fixture
async def enterprise_workspace() -> EnterpriseFixture:
    """Seed a single workspace with the post-connector-removal shape."""
    # Use per-test email suffixes so re-runs don't collide on the unique
    # ``app_user.email`` constraint — without unique emails the INSERTs
    # silently skip and the workspace_member FK fails.
    suffix = uuid4().hex[:8]
    owner_id = str(uuid4())
    admin_id = str(uuid4())
    alice_id = str(uuid4())
    carol_id = str(uuid4())

    owner_email = f"owner-{suffix}@acme.com"
    admin_email = f"admin-{suffix}@acme.com"
    alice_email = f"alice-{suffix}@acme.com"
    carol_email = f"carol-{suffix}@acme.com"

    async with session_scope() as session:
        for uid, email, name in (
            (owner_id, owner_email, "Owner"),
            (admin_id, admin_email, "Admin"),
            (alice_id, alice_email, "Alice"),
            (carol_id, carol_email, "Carol"),
        ):
            await session.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, name) "
                    "VALUES (CAST(:id AS uuid), :email, 'x', :name)"
                ),
                {"id": uid, "email": email, "name": name},
            )

    slug = f"acme-{uuid4().hex[:8]}"
    async with session_scope(user_id=owner_id) as session:
        ws = await create_workspace(
            session, owner_user_id=owner_id, slug=slug, name="Acme"
        )

    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as session:
        for uid, role in (
            (admin_id, "admin"),
            (alice_id, "editor"),
            (carol_id, "editor"),
        ):
            await session.execute(
                text(
                    "INSERT INTO workspace_member (workspace_id, user_id, role) "
                    "VALUES (CAST(:w AS uuid), CAST(:u AS uuid), :r) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"w": ws_id, "u": uid, "r": role},
            )
        await ensure_builtin_actions(session, workspace_id=ws_id)

        pii = await sens_mod.create_label(
            session, workspace_id=ws_id, slug="pii", name="PII",
            description="Personally identifiable information",
        )
        public = await sens_mod.create_label(
            session, workspace_id=ws_id, slug="public", name="Public",
        )
        await sens_mod.create_policy(
            session,
            workspace_id=ws_id,
            name="pii-vs-public",
            rule={"kind": "mutually_exclusive", "labels": ["pii", "public"]},
            action="drop",
        )

    fixture = EnterpriseFixture(
        workspace_id=ws_id,
        slug=slug,
        owner=EnterpriseUser(
            id=owner_id, email=owner_email, role="owner",
        ),
        admin=EnterpriseUser(
            id=admin_id, email=admin_email, role="admin",
        ),
        alice=EnterpriseUser(
            id=alice_id, email=alice_email, role="editor",
        ),
        carol=EnterpriseUser(
            id=carol_id, email=carol_email, role="editor",
        ),
        labels={"pii": pii.id, "public": public.id},
    )

    yield fixture

    # Cleanup.
    async with session_scope() as session:
        await session.execute(
            text("DELETE FROM workspace WHERE id = :id"), {"id": ws_id}
        )
