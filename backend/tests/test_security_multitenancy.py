"""Multi-tenancy regression tests — security-critical.

These guard the boundary that separates workspace A's data from
workspace B's. The failures they catch are hard to notice manually
because RLS does its job on every query *except* when the tenancy
variable is set from user-controlled input without a membership check.

Covers:

- Forging `X-Workspace-Id` against a workspace the user is not a member
  of returns 403.
- Forging `workspace_id` in the JWT claim (minted by the web token
  route from an untrusted query param) returns 403.
- `GET /api/workspaces/{id}` rejects a URL that doesn't match the
  principal's selected workspace.
- `PATCH /api/workspaces/{id}` rejects a URL that doesn't match.
- Session JWTs missing the `aud` claim are rejected.
- Session JWTs with a wrong `aud` are rejected.
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


def _bearer(
    user_id: str,
    *,
    workspace_id: str | None = None,
    aud: str | None | object = ...,
) -> str:
    """Build a session-style JWT. Set `aud=None` to OMIT the claim;
    pass a string to override it. Default matches the canonical MCP URL.
    """
    settings = get_settings()
    claims = {
        "sub": user_id,
        "email": f"sec-{user_id}@example.com",
        "iss": settings.jwt_issuer,
        "exp": 9999999999,
    }
    if workspace_id:
        claims["workspace_id"] = workspace_id
    if aud is ...:
        claims["aud"] = settings.mcp_resource_url
    elif aud is not None:
        claims["aud"] = aud
    token = jwt.encode(
        claims, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    return f"Bearer {token}"


@pytest_asyncio.fixture
async def two_workspaces():
    """Create two workspaces, each with a different owner.

    Returns (alice_ws, bob_ws) where each is {workspace_id, user_id}.
    """
    settings = get_settings()
    alice_id = str(uuid4())
    bob_id = str(uuid4())

    async with session_scope() as session:
        for uid, email in ((alice_id, "alice"), (bob_id, "bob")):
            await session.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, name) "
                    "VALUES (CAST(:id AS uuid), :email, 'x', :name) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": uid,
                    "email": f"{email}-{uid}@example.com",
                    "name": email.title(),
                },
            )

    async with session_scope(user_id=alice_id) as session:
        alice_ws = await create_workspace(
            session, owner_user_id=alice_id,
            slug=f"sec-a-{uuid4().hex[:8]}", name="Alice WS",
        )
    async with session_scope(user_id=bob_id) as session:
        bob_ws = await create_workspace(
            session, owner_user_id=bob_id,
            slug=f"sec-b-{uuid4().hex[:8]}", name="Bob WS",
        )

    yield (
        {"workspace_id": alice_ws.id, "user_id": alice_id},
        {"workspace_id": bob_ws.id, "user_id": bob_id},
    )

    async with session_scope() as session:
        for ws_id in (alice_ws.id, bob_ws.id):
            await session.execute(
                text("DELETE FROM workspace WHERE id = :id"), {"id": ws_id}
            )

    _ = settings  # silence unused warning when settings isn't needed


@pytest.mark.asyncio
async def test_forged_header_cross_workspace_access_is_denied(two_workspaces):
    alice, bob = two_workspaces
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            # Alice's JWT with Bob's workspace in the header.
            "Authorization": _bearer(alice["user_id"]),
            "X-Workspace-Id": bob["workspace_id"],
        },
    ) as ac:
        # Any endpoint that relies on workspace scoping should refuse.
        r = await ac.get("/api/ontology/snapshot")
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_forged_jwt_workspace_claim_is_denied(two_workspaces):
    alice, bob = two_workspaces
    # The web token route will stamp whatever workspace the browser sends
    # via ?workspace=. We simulate that by embedding Bob's workspace in
    # Alice's JWT.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer(
                alice["user_id"], workspace_id=bob["workspace_id"]
            ),
        },
    ) as ac:
        r = await ac.get("/api/ontology/snapshot")
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_get_workspace_rejects_unmatched_path(two_workspaces):
    alice, bob = two_workspaces
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer(
                alice["user_id"], workspace_id=alice["workspace_id"]
            ),
            "X-Workspace-Id": alice["workspace_id"],
        },
    ) as ac:
        # Authenticated as Alice's workspace, but asking for Bob's.
        r = await ac.get(f"/api/workspaces/{bob['workspace_id']}")
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_patch_workspace_rejects_unmatched_path(two_workspaces):
    alice, bob = two_workspaces
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer(
                alice["user_id"], workspace_id=alice["workspace_id"]
            ),
            "X-Workspace-Id": alice["workspace_id"],
        },
    ) as ac:
        r = await ac.patch(
            f"/api/workspaces/{bob['workspace_id']}",
            json={"name": "pwned"},
        )
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_jwt_without_aud_is_rejected(two_workspaces):
    alice, _ = two_workspaces
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer(alice["user_id"], aud=None),
            "X-Workspace-Id": alice["workspace_id"],
        },
    ) as ac:
        r = await ac.get("/api/ontology/snapshot")
        assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_jwt_with_wrong_aud_is_rejected(two_workspaces):
    alice, _ = two_workspaces
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer(
                alice["user_id"], aud="https://other.example.com/api/mcp"
            ),
            "X-Workspace-Id": alice["workspace_id"],
        },
    ) as ac:
        r = await ac.get("/api/ontology/snapshot")
        assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_own_workspace_access_still_works(two_workspaces):
    alice, _ = two_workspaces
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer(
                alice["user_id"], workspace_id=alice["workspace_id"]
            ),
            "X-Workspace-Id": alice["workspace_id"],
        },
    ) as ac:
        # Sanity check the fixes didn't break the happy path.
        r = await ac.get(f"/api/workspaces/{alice['workspace_id']}")
        assert r.status_code == 200, r.text
        r = await ac.get("/api/ontology/snapshot")
        assert r.status_code == 200, r.text
