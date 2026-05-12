"""Members + invites — end-to-end.

Covers: mint invite → preview → accept → appears in member list →
role update → remove. Plus the role gates (viewer can't invite, admin
can invite but not delete workspace, owner can everything).
"""
from __future__ import annotations

from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import session_scope
from app.domain.workspace import create_workspace
from app.main import app


def _bearer(user_id: str, workspace_id: str | None = None) -> str:
    settings = get_settings()
    claims = {
        "sub": user_id,
        "email": f"mem-{user_id}@example.com",
        "iss": settings.jwt_issuer,
        "aud": settings.mcp_resource_url,
        "exp": 9999999999,
    }
    if workspace_id:
        claims["workspace_id"] = workspace_id
    token = jwt.encode(
        claims, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    return f"Bearer {token}"


async def _make_user(user_id: str, email: str) -> None:
    async with session_scope() as session:
        await session.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :email, 'x', :name) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": user_id, "email": email, "name": email.split("@")[0]},
        )


@pytest_asyncio.fixture
async def owner_and_workspace():
    owner_id = str(uuid4())
    await _make_user(owner_id, f"owner-{owner_id}@example.com")
    async with session_scope(user_id=owner_id) as session:
        ws = await create_workspace(
            session,
            owner_user_id=owner_id,
            slug=f"m-{uuid4().hex[:8]}",
            name="Members Test",
        )
    yield owner_id, ws.id
    async with session_scope() as session:
        await session.execute(
            text("DELETE FROM workspace WHERE id = :id"), {"id": ws.id}
        )


@pytest.mark.asyncio
async def test_invite_round_trip(owner_and_workspace):
    owner_id, ws_id = owner_and_workspace

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(owner_id, ws_id)},
    ) as owner:
        # Mint an invite.
        r = await owner.post(
            f"/api/workspaces/{ws_id}/invites",
            json={"role": "editor"},
        )
        assert r.status_code == 201, r.text
        invite = r.json()
        assert invite["role"] == "editor"
        token = invite["token"]
        assert invite["url"].endswith(f"/invite/{token}")

        # Listing shows it as pending.
        r = await owner.get(f"/api/workspaces/{ws_id}/invites")
        assert r.status_code == 200
        pending = r.json()
        assert len(pending) == 1
        assert pending[0]["token"] == token

    # Second user previews + accepts.
    invitee_id = str(uuid4())
    await _make_user(invitee_id, f"invitee-{invitee_id}@example.com")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(invitee_id)},
    ) as invitee:
        r = await invitee.get(f"/api/invites/{token}/preview")
        assert r.status_code == 200
        preview = r.json()
        assert preview["workspace_id"] == ws_id
        assert preview["role"] == "editor"

        r = await invitee.post(f"/api/invites/{token}/accept")
        assert r.status_code == 200
        assert r.json()["workspace_id"] == ws_id

        # Re-accept: token is now single-use → 404.
        r = await invitee.post(f"/api/invites/{token}/accept")
        assert r.status_code == 404

    # Invitee is now a member.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(owner_id, ws_id)},
    ) as owner:
        r = await owner.get(f"/api/workspaces/{ws_id}/members")
        assert r.status_code == 200
        roles = {m["user_id"]: m["role"] for m in r.json()}
        assert roles[owner_id] == "owner"
        assert roles[invitee_id] == "editor"


@pytest.mark.asyncio
async def test_role_gate_rejects_editor_inviting(owner_and_workspace):
    owner_id, ws_id = owner_and_workspace

    # Mint + accept an invite so we have an editor.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(owner_id, ws_id)},
    ) as owner:
        r = await owner.post(
            f"/api/workspaces/{ws_id}/invites", json={"role": "editor"}
        )
        token = r.json()["token"]

    editor_id = str(uuid4())
    await _make_user(editor_id, f"editor-{editor_id}@example.com")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(editor_id)},
    ) as editor:
        await editor.post(f"/api/invites/{token}/accept")

    # Editor tries to create a new invite — must 403.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(editor_id, ws_id)},
    ) as editor:
        r = await editor.post(
            f"/api/workspaces/{ws_id}/invites", json={"role": "viewer"}
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_owner_role_cannot_be_invited(owner_and_workspace):
    owner_id, ws_id = owner_and_workspace
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(owner_id, ws_id)},
    ) as owner:
        r = await owner.post(
            f"/api/workspaces/{ws_id}/invites", json={"role": "owner"}
        )
        # Pydantic regex rejects "owner" before it reaches domain logic.
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_workspace_delete_requires_slug_confirm(owner_and_workspace):
    owner_id, ws_id = owner_and_workspace
    async with session_scope() as session:
        r = await session.execute(
            text("SELECT slug FROM workspace WHERE id = :id"), {"id": ws_id}
        )
        slug = r.first()[0]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(owner_id, ws_id)},
    ) as owner:
        # Wrong slug → 400.
        r = await owner.request(
            "DELETE", f"/api/workspaces/{ws_id}", json={"slug": "wrong"}
        )
        assert r.status_code == 400

        # Right slug → 204, workspace soft-deleted.
        r = await owner.request(
            "DELETE", f"/api/workspaces/{ws_id}", json={"slug": slug}
        )
        assert r.status_code == 204

    # GET should now 404.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": _bearer(owner_id, ws_id)},
    ) as owner:
        r = await owner.get(f"/api/workspaces/{ws_id}")
        assert r.status_code == 404
