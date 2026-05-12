"""End-to-end test of the Drive connector + ACL filter.

Exercises the full loop without real Google credentials:

* Install the Drive connector via the public REST API.
* Complete the OAuth callback (``MOCK_DRIVE=1`` short-circuits the real
  exchange).
* Run the crawler inline so 3 mock documents land as ``episode`` rows
  with their normalized ``episode_acl`` projections.
* Each test user "Connects Google" — also mocked, fabricates an identity
  from their ``app_user.email``.
* Hit ``GET /api/sources`` as each user and assert the visibility matrix.

The asserts cover all the moving parts:

| Caller            | Identity email  | Role   | Sees                                |
|-------------------|-----------------|--------|-------------------------------------|
| Alice (owner)     | alice@acme.com  | owner  | alpha + bravo + charlie (BYPASS)    |
| Alice-as-editor   | alice@acme.com  | editor | alpha (domain) + bravo (user-list)  |
| Bob               | bob@acme.com    | editor | alpha (domain) only                 |
| Carol             | carol@acme.com  | editor | alpha (domain) + bravo (user-list)  |
| Dan (no identity) | — — —           | editor | nothing                             |

If any of those assertions break, the per-source ACL filter has
regressed and we'd be leaking source content to users who can't see it
in Google.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# MOCK_DRIVE must be set BEFORE Settings is constructed. conftest already
# sets baseline env vars; setting it here too is a belt-and-suspenders so
# the file is robust to test reordering.
os.environ["MOCK_DRIVE"] = "1"

from app.core.config import get_settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.workers.crawler import crawl_initial, crawl_incremental  # noqa: E402

# Re-read settings now that MOCK_DRIVE is set.
get_settings.cache_clear()


def _bearer(user_id: str, email: str) -> str:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "iss": settings.jwt_issuer,
            "aud": settings.mcp_resource_url,
            "exp": 9999999999,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return f"Bearer {token}"


def _client(user_id: str, email: str, workspace_id: str) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={
            "Authorization": _bearer(user_id, email),
            "X-Workspace-Id": workspace_id,
        },
    )


async def _create_member(
    workspace_id: str, *, email: str, role: str
) -> str:
    """Create an app_user + workspace_member, return the user id.

    Email is critical here — the mock identity flow copies it onto the
    user_external_identity row, which is what the ACL filter resolves
    against.
    """
    user_id = str(uuid4())
    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO app_user (id, email, password_hash, name, is_active)
                VALUES (CAST(:id AS uuid), :email, 'x', :name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": user_id, "email": email, "name": email.split("@")[0]},
        )
        await session.execute(
            text(
                """
                INSERT INTO workspace_member (workspace_id, user_id, role)
                VALUES (CAST(:w AS uuid), CAST(:u AS uuid), :r)
                ON CONFLICT DO NOTHING
                """
            ),
            {"w": workspace_id, "u": user_id, "r": role},
        )
    return user_id


@pytest_asyncio.fixture
async def stub_arq(monkeypatch):
    """Replace Arq enqueues with no-ops so the test doesn't depend on a
    running worker. The test drives ``crawl_initial`` directly instead.
    """
    async def fake_enqueue_initial(*, connector_instance_id: str) -> str:
        return "test-job-initial"

    async def fake_enqueue_extraction(**kwargs) -> None:
        return None

    async def fake_self_enqueue(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        "app.api.rest.connectors.enqueue_crawl_initial", fake_enqueue_initial
    )
    monkeypatch.setattr(
        "app.workers.crawler.enqueue_extraction", fake_enqueue_extraction
    )
    monkeypatch.setattr(
        "app.workers.crawler._enqueue_self", fake_self_enqueue
    )


@pytest.mark.asyncio
async def test_drive_connector_visibility_matrix(workspace, stub_arq):
    ws_id = workspace["workspace_id"]
    alice_id = workspace["user_id"]

    # Use a workspace-unique domain so this test is isolation-safe and
    # the emails won't collide with other test runs. The mock connector
    # rewrites its ACLs to use this domain too.
    suffix = str(uuid4()).split("-")[0]
    domain = f"acme-{suffix}.test"
    alice_email = f"alice@{domain}"
    bob_email = f"bob@{domain}"
    carol_email = f"carol@{domain}"
    dan_email = f"dan@{domain}"
    hr_email = f"hr@{domain}"

    # Set Alice's email so her identity bridge will be alice@<domain>.
    async with session_scope() as session:
        await session.execute(
            text(
                "UPDATE app_user SET email = :email WHERE id = CAST(:id AS uuid)"
            ),
            {"email": alice_email, "id": alice_id},
        )

    # Add three editors. Bob is in no per-doc ACL (sees only domain-shared).
    # Carol is on the bravo-team list. Dan never connects an identity.
    bob_id = await _create_member(ws_id, email=bob_email, role="editor")
    carol_id = await _create_member(ws_id, email=carol_email, role="editor")
    dan_id = await _create_member(ws_id, email=dan_email, role="editor")

    # Patch the mock data to reference our isolation-safe email/domain.
    import app.connectors._drive_mock as drive_mock
    from app.connectors.base import ACLEntry

    original_initial = drive_mock.initial_items

    def _patched_initial():
        items = original_initial()
        # Item 0: alpha-shared — domain
        items[0].acl.clear()
        items[0].acl.append(ACLEntry(kind="domain", external_id=domain, role="reader"))
        # Item 1: bravo-team — alice + carol
        items[1].acl.clear()
        items[1].acl.append(ACLEntry(kind="user", external_id=alice_email, role="writer"))
        items[1].acl.append(ACLEntry(kind="user", external_id=carol_email, role="reader"))
        # Item 2: charlie-private — hr only
        items[2].acl.clear()
        items[2].acl.append(ACLEntry(kind="user", external_id=hr_email, role="reader"))
        return items

    drive_mock.initial_items = _patched_initial

    alice_owner = _client(alice_id, alice_email, ws_id)
    bob = _client(bob_id, bob_email, ws_id)
    carol = _client(carol_id, carol_email, ws_id)
    dan = _client(dan_id, dan_email, ws_id)

    try:
        # ------------------------------------------------------------------
        # 1. Alice installs the Drive connector.
        # ------------------------------------------------------------------
        resp = await alice_owner.post(
            "/api/connectors",
            json={"kind": "google_drive", "display_name": "Test Drive"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        instance_id = body["instance"]["id"]
        assert body["instance"]["status"] == "authorizing"
        # In mock mode the authorize URL points at our own callback with code embedded.
        parsed = urlparse(body["authorize_url"])
        qs = parse_qs(parsed.query)
        assert qs["code"] == ["mock-code"]
        assert qs["state"] == [instance_id]

        # ------------------------------------------------------------------
        # 2. Complete the OAuth callback (mock-code is accepted by the
        #    mock connector). The endpoint persists encrypted credentials,
        #    flips status → active, and would enqueue crawl_initial
        #    (stubbed away in this fixture).
        # ------------------------------------------------------------------
        resp = await alice_owner.post(
            f"/api/connectors/{instance_id}/oauth-callback",
            json={"code": "mock-code", "state": instance_id},
        )
        assert resp.status_code == 200, resp.text

        # Confirm credentials are now stored.
        async with session_scope(workspace_id=ws_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, credentials_encrypted IS NOT NULL AS has_creds "
                        "FROM connector_instance WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": instance_id},
                )
            ).mappings().one()
            assert row["status"] == "active"
            assert row["has_creds"] is True

        # ------------------------------------------------------------------
        # 3. Drive the crawler inline. Yields 3 mock documents → upserts
        #    episodes + episode_acl rows.
        # ------------------------------------------------------------------
        # CONNECTOR_SECRET_KEY required to decrypt the bundle we just stored.
        # conftest doesn't set it; do it here.
        os.environ.setdefault("CONNECTOR_SECRET_KEY", "test-key")
        get_settings.cache_clear()

        counts = await crawl_initial({}, connector_instance_id=instance_id)
        assert counts["created"] == 3, counts
        assert counts["errors"] == 0

        # Sanity-check episode + ACL projection.
        async with session_scope(workspace_id=ws_id) as session:
            ext_ids = {
                r[0]
                for r in (
                    await session.execute(
                        text(
                            "SELECT external_id FROM episode "
                            "WHERE connector_instance_id = CAST(:id AS uuid) "
                            "AND deleted_at IS NULL"
                        ),
                        {"id": instance_id},
                    )
                )
            }
            assert ext_ids == {"alpha-shared", "bravo-team", "charlie-private"}

            acl_rows = (
                await session.execute(
                    text(
                        """
                        SELECT episode.external_id, ea.principal_kind,
                               ea.principal_external_id
                        FROM episode_acl ea
                        JOIN episode ON episode.id = ea.episode_id
                        WHERE episode.connector_instance_id = CAST(:id AS uuid)
                        ORDER BY episode.external_id, ea.principal_kind, ea.principal_external_id
                        """
                    ),
                    {"id": instance_id},
                )
            ).all()
            acl_set = {(r[0], r[1], r[2]) for r in acl_rows}
            assert ("alpha-shared", "domain", domain) in acl_set
            assert ("bravo-team", "user", alice_email) in acl_set
            assert ("bravo-team", "user", carol_email) in acl_set
            assert ("charlie-private", "user", hr_email) in acl_set

        # ------------------------------------------------------------------
        # 4. Each user (except Dan) connects their Google identity.
        # ------------------------------------------------------------------
        async def _connect_identity(c: AsyncClient) -> None:
            r1 = await c.post("/api/identity/google/authorize-url")
            assert r1.status_code == 200, r1.text
            url = r1.json()["url"]
            qs = parse_qs(urlparse(url).query)
            r2 = await c.post(
                "/api/identity/google/callback",
                json={"code": "mock-id", "state": qs["state"][0]},
            )
            assert r2.status_code == 200, r2.text
            assert r2.json()["external_email"] is not None

        await _connect_identity(alice_owner)
        await _connect_identity(bob)
        await _connect_identity(carol)
        # Dan deliberately does NOT connect.

        async with session_scope(workspace_id=ws_id) as session:
            n = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM user_external_identity "
                        "WHERE workspace_id = CAST(:ws AS uuid)"
                    ),
                    {"ws": ws_id},
                )
            ).scalar_one()
            assert n == 3, "alice + bob + carol should each have one identity"

        # ------------------------------------------------------------------
        # 5. Visibility matrix.
        # ------------------------------------------------------------------
        async def visible_external_ids(c: AsyncClient) -> set[str]:
            r = await c.get("/api/sources")
            assert r.status_code == 200, r.text
            return {row["external_id"] for row in r.json()}

        # Alice as owner: ACL bypass — sees everything.
        assert await visible_external_ids(alice_owner) == {
            "alpha-shared", "bravo-team", "charlie-private",
        }

        # Bob (editor, bob@acme.com): only alpha (domain acme.com matches).
        assert await visible_external_ids(bob) == {"alpha-shared"}

        # Carol (editor, carol@acme.com): alpha (domain) + bravo (direct).
        assert await visible_external_ids(carol) == {"alpha-shared", "bravo-team"}

        # Dan (editor, no identity): sees nothing connector-derived.
        assert await visible_external_ids(dan) == set()

        # ------------------------------------------------------------------
        # 5b. Edge visibility — the actual product surface. /api/edges
        #     hits the same ACL clause as MCP search_memory. Each user's
        #     edge set should match their visible source set.
        # ------------------------------------------------------------------
        async def visible_edge_facts(c: AsyncClient) -> set[str]:
            r = await c.get("/api/edges?limit=50")
            assert r.status_code == 200, r.text
            return {row["fact"] for row in r.json()}

        bob_facts = await visible_edge_facts(bob)
        carol_facts = await visible_edge_facts(carol)
        dan_facts = await visible_edge_facts(dan)
        alice_facts = await visible_edge_facts(alice_owner)

        # Bob (alpha-shared only) sees Engineering membership facts but
        # NOT bravo-team's per-person ownership facts.
        assert any("Engineering" in f for f in bob_facts)
        assert not any("connector framework" in f.lower() for f in bob_facts)

        # Carol (alpha + bravo) sees the bravo facts too.
        assert any("ACL filter" in f for f in carol_facts)

        # Dan (no identity) sees no connector-derived facts.
        assert not any("Engineering" in f for f in dan_facts)

        # Alice (owner) bypasses ACL and sees the charlie-private fact.
        assert any("Staff Engineer" in f for f in alice_facts)

        # ------------------------------------------------------------------
        # 6. Audit log was written for the install + oauth + crawl + identities.
        # ------------------------------------------------------------------
        async with session_scope(workspace_id=ws_id) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT action FROM audit_log
                        WHERE workspace_id = CAST(:ws AS uuid)
                          AND (action LIKE 'connector.%' OR action LIKE 'identity.%')
                        """
                    ),
                    {"ws": ws_id},
                )
            ).all()
            actions = {r[0] for r in rows}
            assert "connector.create" in actions
            assert "connector.oauth.completed" in actions
            assert "connector.initial_crawl.completed" in actions
            assert "identity.connect" in actions

            # Canned facts should have produced edges rooted at the three
            # mock episodes. This is the proof the demo loop has
            # something to ACL-filter — without it, /api/sources/{id}
            # returns derived_edges=[] and the visibility matrix above is
            # vacuous (we'd be filtering an empty set).
            edge_count = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM edge e
                        JOIN episode ep ON ep.id = e.source_id
                        WHERE ep.connector_instance_id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": instance_id},
                )
            ).scalar_one()
            assert edge_count >= 9, (
                f"expected at least 9 canned edges across 3 episodes, got {edge_count}"
            )

        # ------------------------------------------------------------------
        # 7. Soft-deleting the connector hides its source documents from
        #    everyone (including admins): the listing JOINs ci.deleted_at IS NULL.
        # ------------------------------------------------------------------
        resp = await alice_owner.delete(f"/api/connectors/{instance_id}")
        assert resp.status_code == 204
        post_delete = await visible_external_ids(alice_owner)
        assert post_delete == set(), f"after soft-delete still saw: {post_delete}"

    finally:
        drive_mock.initial_items = original_initial
        await alice_owner.aclose()
        await bob.aclose()
        await carol.aclose()
        await dan.aclose()


@pytest.mark.asyncio
async def test_incremental_crawl_diffs_existing_documents(workspace, stub_arq):
    """A second incremental tick should detect the synthetic edit of
    alpha-shared and the deletion of charlie-private wired in the mock.
    """
    ws_id = workspace["workspace_id"]
    alice_id = workspace["user_id"]
    alice = _client(alice_id, "alice@acme.com", ws_id)

    try:
        resp = await alice.post(
            "/api/connectors",
            json={"kind": "google_drive", "display_name": "T"},
        )
        instance_id = resp.json()["instance"]["id"]
        await alice.post(
            f"/api/connectors/{instance_id}/oauth-callback",
            json={"code": "mock-code", "state": instance_id},
        )

        os.environ.setdefault("CONNECTOR_SECRET_KEY", "test-key")
        get_settings.cache_clear()

        # Initial crawl seeds 3 episodes; sets cursor.mock_tick = 0.
        await crawl_initial({}, connector_instance_id=instance_id)

        # Tick 0 → no changes.
        counts0 = await crawl_incremental(
            {}, connector_instance_id=instance_id
        )
        assert counts0["updated"] == 0
        assert counts0["deleted"] == 0

        # Tick 1 → alpha-shared edited.
        counts1 = await crawl_incremental(
            {}, connector_instance_id=instance_id
        )
        assert counts1["updated"] == 1
        assert counts1["deleted"] == 0

        # Tick 2 → charlie-private deleted.
        counts2 = await crawl_incremental(
            {}, connector_instance_id=instance_id
        )
        assert counts2["deleted"] == 1

        # The deleted episode should be soft-deleted (deleted_at set), not gone.
        async with session_scope(workspace_id=ws_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT deleted_at FROM episode "
                        "WHERE external_id = 'charlie-private' "
                        "AND connector_instance_id = CAST(:id AS uuid)"
                    ),
                    {"id": instance_id},
                )
            ).first()
            assert row is not None
            assert row[0] is not None
    finally:
        await alice.aclose()
