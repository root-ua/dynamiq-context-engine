"""Q5 — JSON-LD content negotiation across the read surface.

Walks every primary read endpoint with ``Accept: application/ld+json``
and validates the @context + key fields the audit asked for.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain.workspace import create_workspace
from app.main import app

pytestmark = pytest.mark.scenario


def _bearer(user_id: str, workspace_id: str) -> str:
    import jwt
    settings = get_settings()
    return "Bearer " + jwt.encode(
        {
            "sub": user_id,
            "email": f"q5-{user_id}@x.com",
            "workspace_id": workspace_id,
            "iss": settings.jwt_issuer,
            "aud": settings.mcp_resource_url,
            "exp": 9999999999,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest_asyncio.fixture
async def q5_workspace():
    user_id = str(uuid4())
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :email, 'x', 'T')"
            ),
            {"id": user_id, "email": f"q5-{user_id}@x.com"},
        )
    slug = f"q5-{uuid4().hex[:6]}"
    async with session_scope(user_id=user_id) as s:
        ws = await create_workspace(
            s, owner_user_id=user_id, slug=slug, name="Q5",
        )
    async with session_scope(workspace_id=ws.id, user_id=user_id) as s:
        alice = await entity_mod.create(
            s, workspace_id=ws.id, type_ref="person",
            canonical="Alice Q5", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws.id, type_ref="organization",
            canonical="Acme Q5", embed=False,
        )
        edge = await edge_mod.add_fact(
            s, workspace_id=ws.id,
            subject_id=alice.id, predicate="works_at", object_id=acme.id,
            fact="Alice Q5 works at Acme Q5",
            embed=False, run_contradictor=False,
        )
    yield {
        "user_id": user_id, "ws_id": ws.id,
        "alice": alice.id, "acme": acme.id, "edge": edge.id,
    }
    async with session_scope() as s:
        await s.execute(
            text("DELETE FROM workspace WHERE id = :id"), {"id": ws.id}
        )


def _headers(fx: dict) -> dict[str, str]:
    return {
        "Authorization": _bearer(fx["user_id"], fx["ws_id"]),
        "X-Workspace-Id": fx["ws_id"],
        "Accept": "application/ld+json",
    }


@pytest.mark.asyncio
async def test_full_read_surface_emits_jsonld(q5_workspace):
    """Hit every primary read endpoint and assert the @context is
    present and complete."""
    fx = q5_workspace
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Entity
        r_ent = await ac.get(
            f"/api/entities/{fx['acme']}", headers=_headers(fx),
        )
        # Edge
        r_edge = await ac.get(
            f"/api/edges/{fx['edge']}", headers=_headers(fx),
        )
        # Ontology snapshot
        r_snap = await ac.get(
            "/api/ontology/snapshot", headers=_headers(fx),
        )
        # Ontology types list
        r_types = await ac.get(
            "/api/ontology/types", headers=_headers(fx),
        )
        # Ontology relations list
        r_rels = await ac.get(
            "/api/ontology/relations", headers=_headers(fx),
        )
        # Graph traverse
        r_graph = await ac.post(
            "/api/graph/traverse",
            headers=_headers(fx),
            json={"seeds": [fx["alice"]], "max_hops": 1},
        )

    for resp in (r_ent, r_edge, r_snap, r_types, r_rels, r_graph):
        assert resp.status_code == 200, resp.text
        ctx = resp.json().get("@context")
        assert ctx, resp.text
        for prefix in ("prov", "owl", "rdfs", "skos"):
            assert prefix in ctx, (prefix, ctx)
