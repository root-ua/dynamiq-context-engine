"""External MCP clients (Claude Web's Custom Connectors, Cursor, …)
discover this server by hitting three URLs without auth:

1. ``GET /api/mcp/rpc`` — liveness + protocol version advertisement.
2. ``GET /.well-known/oauth-protected-resource`` — RFC 9728 metadata.
3. ``GET /health`` — operator probe used by uptime monitors.

If any of those return 401 the discovery breaks. This test pins the
contract so future auth-tightening passes don't accidentally close
them off.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_health_is_anonymous(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "ok"


def test_mcp_rpc_liveness_is_anonymous(client: TestClient) -> None:
    r = client.get("/api/mcp/rpc")
    assert r.status_code == 200, r.text
    body = r.json()
    # The probe must advertise the MCP protocol version so a Claude
    # Web Connector form knows it's reached an MCP server.
    assert "protocolVersion" in body or "version" in body


def test_oauth_protected_resource_metadata_is_anonymous(
    client: TestClient,
) -> None:
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200, r.text
    body = r.json()
    # Required fields per RFC 9728 for an MCP resource server.
    assert "resource" in body
    assert "authorization_servers" in body or "bearer_methods_supported" in body
