"""B1 — Document REST endpoints must reject cross-workspace document IDs.

The audit found that `get_doc`, `delete_doc`, `get_blocks`,
`replace_blocks`, `list_revisions`, `create_revision`, and
`restore_revision` accepted a `document_id` from the URL without
verifying it belonged to the principal's workspace. With RLS bypassed
for the test/dev role, that meant any authenticated user could read or
edit any document in any workspace.

These tests pin every document endpoint to "404 if the document lives
in a different workspace".
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import session_scope
from app.domain import document as doc_mod
from app.domain.workspace import create_workspace
from app.main import app


def _bearer(user_id: str, workspace_id: str) -> str:
    import jwt
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": user_id,
            "email": f"u-{user_id}@x.com",
            "workspace_id": workspace_id,
            "iss": settings.jwt_issuer,
            "aud": settings.mcp_resource_url,
            "exp": 9999999999,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return f"Bearer {token}"


@pytest_asyncio.fixture
async def two_ws_with_doc():
    """Workspace A has a document; user B is a member of workspace B only."""
    alice_id = str(uuid4())
    bob_id = str(uuid4())
    async with session_scope() as s:
        for uid, email in ((alice_id, "alice"), (bob_id, "bob")):
            await s.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, name) "
                    "VALUES (CAST(:id AS uuid), :email, 'x', :name)"
                ),
                {"id": uid, "email": f"iso-{uid}@x.com", "name": email},
            )
    async with session_scope(user_id=alice_id) as s:
        ws_a = await create_workspace(
            s, owner_user_id=alice_id,
            slug=f"a-{uuid4().hex[:6]}", name="A",
        )
    async with session_scope(user_id=bob_id) as s:
        ws_b = await create_workspace(
            s, owner_user_id=bob_id,
            slug=f"b-{uuid4().hex[:6]}", name="B",
        )
    async with session_scope(workspace_id=ws_a.id, user_id=alice_id) as s:
        doc = await doc_mod.create_document(
            s,
            workspace_id=ws_a.id,
            title="Secret plan",
            type_slug="document",
            created_by=alice_id,
        )

    yield {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "ws_a": ws_a.id,
        "ws_b": ws_b.id,
        "doc_id": doc.id,
    }

    async with session_scope() as s:
        for wid in (ws_a.id, ws_b.id):
            await s.execute(
                text("DELETE FROM workspace WHERE id = :id"), {"id": wid}
            )


@pytest.mark.parametrize(
    "method,path_tail,body",
    [
        ("GET", "", None),
        ("DELETE", "", None),
        ("GET", "/blocks", None),
        ("PUT", "/blocks", {"blocks": []}),
        ("GET", "/revisions", None),
        ("POST", "/revisions", {"note": "x"}),
    ],
)
@pytest.mark.asyncio
async def test_cross_workspace_document_access_denied(
    two_ws_with_doc, method, path_tail, body
):
    """Bob (workspace B) must NOT touch Alice's doc (workspace A)."""
    fx = two_ws_with_doc
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        url = f"/api/documents/{fx['doc_id']}{path_tail}"
        headers = {
            "Authorization": _bearer(fx["bob_id"], fx["ws_b"]),
            "X-Workspace-Id": fx["ws_b"],
        }
        if method == "GET":
            resp = await ac.get(url, headers=headers)
        elif method == "DELETE":
            resp = await ac.delete(url, headers=headers)
        elif method == "PUT":
            resp = await ac.put(url, headers=headers, json=body)
        elif method == "POST":
            resp = await ac.post(url, headers=headers, json=body)
        else:
            raise AssertionError(method)
    assert resp.status_code == 404, (
        f"{method} {url} returned {resp.status_code} {resp.text}"
    )


@pytest.mark.asyncio
async def test_cross_workspace_restore_denied(two_ws_with_doc):
    """Restore endpoint takes two IDs in the URL; both must be checked."""
    fx = two_ws_with_doc
    # Create a revision so the URL doesn't 404 for an unrelated reason.
    async with session_scope(workspace_id=fx["ws_a"], user_id=fx["alice_id"]) as s:
        rev_id = await doc_mod.snapshot_revision(
            s, document_id=fx["doc_id"], actor_id=fx["alice_id"], note="r1"
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            f"/api/documents/{fx['doc_id']}/revisions/{rev_id}/restore",
            headers={
                "Authorization": _bearer(fx["bob_id"], fx["ws_b"]),
                "X-Workspace-Id": fx["ws_b"],
            },
        )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_same_workspace_access_still_works(two_ws_with_doc):
    """The owner of the doc must still get a 200 — we're tightening the
    door, not slamming it shut on legitimate callers."""
    fx = two_ws_with_doc
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/documents/{fx['doc_id']}",
            headers={
                "Authorization": _bearer(fx["alice_id"], fx["ws_a"]),
                "X-Workspace-Id": fx["ws_a"],
            },
        )
    assert resp.status_code == 200, resp.text
