"""Phase N — JSON-LD content negotiation.

Every primary read endpoint emits a JSON-LD document when called with
``Accept: application/ld+json`` (or ``?format=jsonld``). The shape
follows the @context defined in ``app.jsonld``.

These tests cover the cross-cutting expectations: every response carries
prov:/owl:/rdfs:/skos: prefixes; entity types come back as owl:Class with
rdfs:subClassOf; relations carry owl:inverseOf when set; entities with
external refs emit owl:sameAs.
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
from app.domain import entity_resolver as resolver_mod
from app.domain import episode as episode_mod
from app.domain.workspace import create_workspace
from app.main import app


def _bearer(user_id: str, workspace_id: str) -> str:
    import jwt
    settings = get_settings()
    return "Bearer " + jwt.encode(
        {
            "sub": user_id,
            "email": f"jl-{user_id}@x.com",
            "workspace_id": workspace_id,
            "iss": settings.jwt_issuer,
            "aud": settings.mcp_resource_url,
            "exp": 9999999999,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest_asyncio.fixture
async def seeded_workspace():
    user_id = str(uuid4())
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :email, 'x', 'T')"
            ),
            {"id": user_id, "email": f"jl-{user_id}@x.com"},
        )
    slug = f"jl-{uuid4().hex[:8]}"
    async with session_scope(user_id=user_id) as s:
        ws = await create_workspace(
            s, owner_user_id=user_id, slug=slug, name="JL",
        )
    async with session_scope(workspace_id=ws.id, user_id=user_id) as s:
        alice = await entity_mod.create(
            s, workspace_id=ws.id, type_ref="person",
            canonical="Alice JL", aliases=["A. JL"], embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws.id, type_ref="organization",
            canonical="Acme JL", embed=False,
        )
        # External refs so we can exercise owl:sameAs.
        await resolver_mod.add_external_ref(
            s, workspace_id=ws.id, entity_id=acme.id,
            kind="wikidata", value="Q123",
        )
        await resolver_mod.add_external_ref(
            s, workspace_id=ws.id, entity_id=acme.id,
            kind="email", value="contact@acme.example",
        )
        # An edge with a clear inverse_of slug (works_at ↔ employs).
        e = await edge_mod.add_fact(
            s, workspace_id=ws.id,
            subject_id=alice.id, predicate="works_at", object_id=acme.id,
            fact="Alice works at Acme",
            embed=False, run_contradictor=False,
        )
        ep = await episode_mod.add_episode(
            s, workspace_id=ws.id, content="JL episode body.",
            source_kind="agent", embed=False,
        )

    yield {
        "user_id": user_id, "ws_id": ws.id,
        "alice": alice.id, "acme": acme.id,
        "edge": e.id, "episode": ep.id,
    }

    async with session_scope() as s:
        await s.execute(
            text("DELETE FROM workspace WHERE id = :id"), {"id": ws.id}
        )


def _ld_headers(user_id: str, ws_id: str) -> dict[str, str]:
    return {
        "Authorization": _bearer(user_id, ws_id),
        "X-Workspace-Id": ws_id,
        "Accept": "application/ld+json",
    }


def _assert_base_context(doc: dict) -> None:
    ctx = doc.get("@context")
    assert ctx, doc
    assert ctx["prov"] == "http://www.w3.org/ns/prov#"
    assert ctx["owl"] == "http://www.w3.org/2002/07/owl#"
    assert ctx["rdfs"] == "http://www.w3.org/2000/01/rdf-schema#"
    assert ctx["skos"] == "http://www.w3.org/2004/02/skos/core#"


@pytest.mark.asyncio
async def test_entity_jsonld(seeded_workspace):
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/entities/{fx['acme']}",
            headers=_ld_headers(fx["user_id"], fx["ws_id"]),
        )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    _assert_base_context(doc)
    assert doc["@id"].endswith(fx["acme"])
    assert doc["@type"] == "Entity"
    assert doc["prefLabel"] == "Acme JL"
    same_as = doc.get("sameAs") or []
    if isinstance(same_as, str):
        same_as = [same_as]
    # owl:sameAs should include the wikidata + email IRIs.
    assert any(s.startswith("https://www.wikidata.org/") for s in same_as)
    assert any(s.startswith("mailto:") for s in same_as)


@pytest.mark.asyncio
async def test_entity_plain_json_unchanged(seeded_workspace):
    """Without the Accept header we still get the legacy JSON."""
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/entities/{fx['acme']}",
            headers={
                "Authorization": _bearer(fx["user_id"], fx["ws_id"]),
                "X-Workspace-Id": fx["ws_id"],
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "@context" not in body
    assert body["canonical"] == "Acme JL"


@pytest.mark.asyncio
async def test_edge_jsonld(seeded_workspace):
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/edges/{fx['edge']}",
            headers=_ld_headers(fx["user_id"], fx["ws_id"]),
        )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    _assert_base_context(doc)
    assert "dce:Fact" in doc["@type"]
    assert doc["dce:fact"] == "Alice works at Acme"
    assert doc["dce:subject"].endswith(fx["alice"])
    assert doc["dce:object"].endswith(fx["acme"])


@pytest.mark.asyncio
async def test_episode_jsonld(seeded_workspace):
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/episodes/{fx['episode']}",
            headers=_ld_headers(fx["user_id"], fx["ws_id"]),
        )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    _assert_base_context(doc)
    assert "dce:Episode" in doc["@type"]
    assert doc["dce:contentText"] == "JL episode body."


@pytest.mark.asyncio
async def test_ontology_snapshot_jsonld(seeded_workspace):
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/ontology/snapshot",
            headers=_ld_headers(fx["user_id"], fx["ws_id"]),
        )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    _assert_base_context(doc)
    nodes = doc["@graph"]
    types = [n for n in nodes if n["@type"] == "Class"]
    relations = [n for n in nodes if n["@type"] == "ObjectProperty"]
    assert types, "expected at least one owl:Class node"
    assert relations, "expected at least one owl:ObjectProperty node"

    # ``person`` derives from ``agent`` (seeded ontology); the subClassOf
    # link should be present somewhere in the type set.
    type_slugs = {t["dce:slug"]: t for t in types}
    assert "person" in type_slugs
    assert "subClassOf" in type_slugs["person"]

    # ``works_at`` should carry an owl:inverseOf if a matching inverse
    # relation exists in the seed ontology.
    rel_slugs = {r["dce:slug"]: r for r in relations}
    if "works_at" in rel_slugs and "employs" in rel_slugs:
        assert "inverseOf" in rel_slugs["works_at"]


@pytest.mark.asyncio
async def test_graph_traverse_jsonld(seeded_workspace):
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/graph/traverse",
            headers=_ld_headers(fx["user_id"], fx["ws_id"]),
            json={"seeds": [fx["alice"]], "max_hops": 1},
        )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    _assert_base_context(doc)
    assert "@graph" in doc and isinstance(doc["@graph"], list)
    assert any(n["@type"] == "Entity" for n in doc["@graph"])


@pytest.mark.asyncio
async def test_format_query_param(seeded_workspace):
    """``?format=jsonld`` also flips the response (curl-friendly path)."""
    fx = seeded_workspace
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/entities/{fx['acme']}?format=jsonld",
            headers={
                "Authorization": _bearer(fx["user_id"], fx["ws_id"]),
                "X-Workspace-Id": fx["ws_id"],
            },
        )
    assert resp.status_code == 200, resp.text
    assert "@context" in resp.json()
