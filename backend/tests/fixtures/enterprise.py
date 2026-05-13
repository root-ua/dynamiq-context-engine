"""Enterprise-persona scenario fixture.

Pre-seeded workspace shaped like a small enterprise customer:
- 3 users at different roles (admin / editor / editor)
- 3 Google `user_external_identity` rows bridging to the Drive mock's
  ACL principals (alice@, carol@, hr@)
- A registered Drive `connector_instance` in mock mode (real-mode
  connectors are not invoked because ``MOCK_DRIVE`` is read by the
  Drive code paths)
- A registered Notion `connector_instance` in mock mode
- Built-in action types seeded
- `pii` and `public` sensitivity labels + a `mutually_exclusive` drop
  policy ready to demo the governance pitch

Used by ``test_scenario_knowledge_worker.py`` and
``test_scenario_mcp_agent.py``. Each test gets a fresh fixture
(function scope) so seeds don't bleed between tests.
"""
from __future__ import annotations

import os
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
    external_id: str  # mock Drive principal (e.g. 'alice@acme.com')


@dataclass
class EnterpriseFixture:
    workspace_id: str
    slug: str
    owner: EnterpriseUser
    admin: EnterpriseUser
    alice: EnterpriseUser
    carol: EnterpriseUser
    drive_instance_id: str
    notion_instance_id: str
    labels: dict[str, str]  # slug → id


@pytest_asyncio.fixture
async def enterprise_workspace() -> EnterpriseFixture:
    """Seed a single workspace with the shape Phase K / L expects."""
    # Force mock connector modes regardless of caller env. Both flags are
    # read on each call into the connector, so flipping here is safe.
    os.environ["MOCK_DRIVE"] = "1"
    os.environ["MOCK_NOTION"] = "1"

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
        # Add admin / alice / carol as members.
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

        # Bridge identities to the Drive mock's ACL principals. These
        # external_ids are fixed in ``_drive_mock`` (alice@acme.com,
        # carol@acme.com, hr@acme.com) so each test user's bridged
        # identity must match exactly for ACL evaluation to fire.
        for uid, ext in (
            (admin_id, "admin@acme.com"),
            (alice_id, "alice@acme.com"),
            (carol_id, "carol@acme.com"),
        ):
            await session.execute(
                text(
                    """
                    INSERT INTO user_external_identity
                      (user_id, workspace_id, provider, external_id,
                       external_email, groups)
                    VALUES
                      (CAST(:u AS uuid), CAST(:w AS uuid), 'google',
                       :ext, :ext, '[]'::jsonb)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"u": uid, "w": ws_id, "ext": ext},
            )

        # Mock Drive + Notion connector instances. Real OAuth not
        # involved; the mock paths in google_drive / notion read
        # ``MOCK_DRIVE`` / ``MOCK_NOTION`` at runtime.
        drive_row = (
            await session.execute(
                text(
                    """
                    INSERT INTO connector_instance
                      (workspace_id, connector_kind, display_name, status,
                       config, created_by)
                    VALUES
                      (CAST(:w AS uuid), 'google_drive',
                       'Mock Drive', 'active', '{}'::jsonb,
                       CAST(:u AS uuid))
                    RETURNING id::text
                    """
                ),
                {"w": ws_id, "u": owner_id},
            )
        ).first()
        drive_instance_id = drive_row[0]
        notion_row = (
            await session.execute(
                text(
                    """
                    INSERT INTO connector_instance
                      (workspace_id, connector_kind, display_name, status,
                       config, created_by)
                    VALUES
                      (CAST(:w AS uuid), 'notion',
                       'Mock Notion', 'active', '{}'::jsonb,
                       CAST(:u AS uuid))
                    RETURNING id::text
                    """
                ),
                {"w": ws_id, "u": owner_id},
            )
        ).first()
        notion_instance_id = notion_row[0]

        # Labels + a default drop policy.
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
            id=owner_id, email="owner@acme.com", role="owner",
            external_id="owner@acme.com",
        ),
        admin=EnterpriseUser(
            id=admin_id, email="admin@acme.com", role="admin",
            external_id="admin@acme.com",
        ),
        alice=EnterpriseUser(
            id=alice_id, email="alice@acme.com", role="editor",
            external_id="alice@acme.com",
        ),
        carol=EnterpriseUser(
            id=carol_id, email="carol@acme.com", role="editor",
            external_id="carol@acme.com",
        ),
        drive_instance_id=drive_instance_id,
        notion_instance_id=notion_instance_id,
        labels={"pii": pii.id, "public": public.id},
    )

    yield fixture

    # Cleanup.
    async with session_scope() as session:
        await session.execute(
            text("DELETE FROM workspace WHERE id = :id"), {"id": ws_id}
        )
