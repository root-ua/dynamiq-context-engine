"""Round-trip tests for the agent-token surface.

Covers: mint → list → use for MCP request → revoke → fails afterwards.
These are end-to-end through the FastAPI app so RLS, argon2 hashing, and
the two-bearer-kind auth split all get exercised.
"""
from __future__ import annotations

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


def _bearer_jwt(user_id: str, workspace_id: str) -> str:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": user_id,
            "email": f"rest-{user_id}@example.com",
            "iss": settings.jwt_issuer,
            "aud": settings.mcp_resource_url,
            "workspace_id": workspace_id,
            "exp": 9999999999,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return f"Bearer {token}"


@pytest_asyncio.fixture
async def jwt_client(workspace, app_user):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": _bearer_jwt(
                workspace["user_id"], workspace["workspace_id"]
            ),
            "X-Workspace-Id": workspace["workspace_id"],
        },
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def app_user(workspace):
    """Mirror the JWT `sub` into `app_user` — same pattern as the main REST test."""
    from sqlalchemy import text

    from app.db.session import session_scope

    user_id = workspace["user_id"]
    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO app_user (id, email, name)
                VALUES (CAST(:id AS uuid), :email, :name)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": user_id,
                "email": f"rest-{user_id}@example.com",
                "name": "Test",
            },
        )
    return user_id


@pytest.mark.asyncio
async def test_agent_token_mint_list_revoke(jwt_client):
    # Mint
    resp = await jwt_client.post(
        "/api/agent-tokens",
        json={"name": "Claude Code laptop"},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["token"].startswith("mem_")
    assert body["name"] == "Claude Code laptop"
    token_id = body["id"]
    plaintext = body["token"]

    # List — token plaintext must NOT leak
    resp = await jwt_client.get("/api/agent-tokens")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == token_id
    assert "token" not in rows[0]
    assert rows[0]["prefix"] and len(rows[0]["prefix"]) == 8

    # Use plaintext to hit an authed endpoint — pass ONLY the bearer,
    # no X-Workspace-Id (agent tokens carry their own workspace binding).
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as agent_client:
        # Default-scope ('mcp') tokens can hit /api/mcp/* only.
        rpc = await agent_client.post(
            "/api/mcp/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert rpc.status_code == 200
        tools = rpc.json()["result"]["tools"]
        assert len(tools) >= 12
        names = {t["name"] for t in tools}
        assert "search_memory" in names

        # A default-scope agent token must NOT be able to hit non-MCP
        # REST endpoints. This enforces least-privilege: a leaked MCP
        # token can read/write memory through MCP but can't, for example,
        # enumerate ontology types via REST or mint more tokens.
        r = await agent_client.get("/api/ontology/snapshot")
        assert r.status_code == 403
        r = await agent_client.post(
            "/api/agent-tokens", json={"name": "escalation attempt"}
        )
        assert r.status_code == 403

    # Revoke
    resp = await jwt_client.delete(f"/api/agent-tokens/{token_id}")
    assert resp.status_code == 204

    # Revoked token can no longer authenticate
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as agent_client:
        r = await agent_client.post(
            "/api/mcp/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_www_authenticate(jwt_client):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as anon:
        r = await anon.post("/api/mcp/rpc", json={})
        assert r.status_code == 401
        header = r.headers.get("WWW-Authenticate", "")
        assert header.startswith("Bearer")
        assert "resource_metadata=" in header


@pytest.mark.asyncio
async def test_mcp_rpc_probe_accepts_unauthenticated_get():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as anon:
        r = await anon.get("/api/mcp/rpc")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == "2025-06-18"


@pytest.mark.asyncio
async def test_well_known_oauth_protected_resource():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as anon:
        r = await anon.get("/.well-known/oauth-protected-resource")
        assert r.status_code == 200
        body = r.json()
        assert body["resource"].endswith("/api/mcp")
        assert "authorization_servers" in body
        assert body["bearer_methods_supported"] == ["header"]
