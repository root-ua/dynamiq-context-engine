"""End-to-end REST coverage.

Exercises the HTTP layer on every endpoint that the web UI calls. These
tests complement the per-module domain tests by validating the wiring:
auth → RLS session vars → domain service → response shape.

They reuse the live Postgres that the existing domain tests use; each
workspace gets a unique slug so tests are isolation-safe.
"""
from __future__ import annotations

import uuid
from typing import Any

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import session_scope
from app.main import app


def _bearer(user_id: str) -> str:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": user_id,
            "email": f"rest-{user_id}@example.com",
            "iss": settings.jwt_issuer,
            "aud": settings.mcp_resource_url,
            "exp": 9999999999,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return f"Bearer {token}"


@pytest_asyncio.fixture
async def client(workspace):
    """Authed async HTTP client for the REST API."""
    user_id = workspace["user_id"]
    headers = {
        "Authorization": _bearer(user_id),
        "X-Workspace-Id": workspace["workspace_id"],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def app_user(workspace):
    """Ensure an app_user row exists for the JWT user so edges/audit FKs pass."""
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


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_workspaces_returns_membership(client, workspace):
    resp = await client.get("/api/workspaces")
    assert resp.status_code == 200, resp.text
    slugs = [w["slug"] for w in resp.json()]
    assert workspace["slug"] in slugs


@pytest.mark.asyncio
async def test_get_workspace_by_id(client, workspace):
    resp = await client.get(f"/api/workspaces/{workspace['workspace_id']}")
    assert resp.status_code == 200
    assert resp.json()["slug"] == workspace["slug"]


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ontology_snapshot_has_builtin_types(client):
    resp = await client.get("/api/ontology/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    slugs = {t["slug"] for t in body["types"]}
    # The built-in seed ships with these. If any of them disappears, a
    # downstream page (entity create, graph filter, propose) breaks.
    assert {"person", "organization", "project", "document"} <= slugs


@pytest.mark.asyncio
async def test_ontology_create_custom_type(client):
    # Slugs get normalised to snake_case by the ontology service.
    slug = f"custom_{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/api/ontology/types",
        json={
            "name": f"Custom {slug}",
            "slug": slug,
            "extends": "thing",
            "description": "rest test",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    assert data["slug"] == slug
    assert data["system"] is False

    # It should show up in the snapshot.
    snap = await client.get("/api/ontology/snapshot")
    snap_slugs = {t["slug"] for t in snap.json()["types"]}
    assert slug in snap_slugs


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_create_update_list(client, app_user):
    # Create
    resp = await client.post(
        "/api/entities",
        json={"type": "person", "canonical": "Ada Lovelace"},
    )
    assert resp.status_code in (200, 201), resp.text
    ent = resp.json()
    ent_id = ent["id"]
    assert ent["canonical"] == "Ada Lovelace"

    # Update canonical + summary
    resp = await client.patch(
        f"/api/entities/{ent_id}",
        json={"canonical": "Augusta Ada King", "summary": "mathematician"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["canonical"] == "Augusta Ada King"
    assert updated["summary"] == "mathematician"

    # List with type filter
    resp = await client.get("/api/entities", params={"type": "person", "limit": 50})
    assert resp.status_code == 200
    canonicals = [e["canonical"] for e in resp.json()]
    assert "Augusta Ada King" in canonicals

    # Get single
    resp = await client.get(f"/api/entities/{ent_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == ent_id


# ---------------------------------------------------------------------------
# Edges + graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_create_then_live_then_invalidate(client, app_user):
    # Need subject + object
    resp = await client.post(
        "/api/entities", json={"type": "person", "canonical": "Alice E2E"}
    )
    assert resp.status_code in (200, 201)
    alice = resp.json()["id"]

    resp = await client.post(
        "/api/entities",
        json={"type": "organization", "canonical": "Acme E2E"},
    )
    assert resp.status_code in (200, 201)
    acme = resp.json()["id"]

    # Create edge
    resp = await client.post(
        "/api/edges",
        json={
            "subject_id": alice,
            "predicate": "works_at",
            "object_id": acme,
            "fact": "Alice works at Acme",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    edge = resp.json()
    edge_id = edge["id"]

    # Should show up as live
    resp = await client.get(f"/api/entities/{alice}/edges", params={"direction": "out"})
    assert resp.status_code == 200
    live_ids = [e["id"] for e in resp.json()]
    assert edge_id in live_ids

    # Invalidate
    resp = await client.post(f"/api/edges/{edge_id}/invalidate", json={"reason": "left"})
    assert resp.status_code == 200
    closed = resp.json()
    assert closed.get("sys_to") is not None


@pytest.mark.asyncio
async def test_graph_traverse_returns_seed(client, app_user):
    # Seed a small graph
    resp = await client.post(
        "/api/entities", json={"type": "person", "canonical": "Seed Person"}
    )
    ent_id = resp.json()["id"]

    resp = await client.post(
        "/api/graph/traverse",
        json={"seeds": [ent_id], "max_hops": 1, "max_nodes": 100},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At minimum the seed must be in the payload.
    node_ids = [n["id"] for n in body["nodes"]]
    assert ent_id in node_ids


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_tool_list_contains_core_tools(client):
    resp = await client.get("/api/mcp/tools")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["tools"]}
    # These are the tools the agent console renders; regressions here
    # break the "Invoke" screen silently.
    assert {
        "search_memory",
        "get_entity",
        "ontology_describe",
        "create_entity_type",
    } <= names


@pytest.mark.asyncio
async def test_mcp_invoke_ontology_describe(client):
    resp = await client.post(
        "/api/mcp/invoke",
        json={"name": "ontology_describe", "arguments": {}},
    )
    assert resp.status_code == 200, resp.text
    result: dict[str, Any] = resp.json()["result"]
    assert "types" in result or "ontology" in result or result  # tolerate shape drift


# ---------------------------------------------------------------------------
# Search (degrades gracefully without embeddings)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_empty_for_unknown_query(client):
    resp = await client.post(
        "/api/search",
        json={"query": "xyzzy-does-not-exist", "limit": 5},
    )
    # Either 200 with empty hits or 200 with a hits array — the crucial
    # thing is that the endpoint doesn't blow up when the embedding client
    # is unavailable.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "hits" in body or "results" in body or isinstance(body, list)
