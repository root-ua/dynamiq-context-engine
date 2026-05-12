"""ACL filter integration tests.

Exercises the SQL fragment returned by ``app.auth.acl`` against a real
Postgres so we know the JSONB / NULLS-NOT-DISTINCT / EXISTS semantics
behave as designed. Covers:

* Service-kind Principal: bypasses ACL.
* Owner/admin Principal: bypasses ACL.
* User Principal with matching external identity: sees connector
  episode and its derived edge.
* User Principal without an identity bridge: only sees user-asserted
  episodes (and their derived edges).
* Group / domain / 'anyone' ACL entries resolve correctly.
* Soft-deleted episodes are invisible to user kind regardless of ACL.
"""
from __future__ import annotations

from uuid import uuid4

import pytest_asyncio
import pytest
from sqlalchemy import text

from app.auth.acl import edge_visibility_clause, episode_visibility_clause
from app.auth.jwt import Principal
from app.db.session import session_scope


def _principal(user_id: str, ws: str, *, kind: str = "user", role: str | None = None) -> Principal:
    return Principal(
        user_id=user_id,
        email=None,
        workspace_id=ws,
        role=role,
        claims={},
        kind=kind,  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def acl_fixture(workspace, two_people):
    """Builds a fixture with:

    - workspace with two users (creator = alice; bob added as editor)
    - one user-asserted episode (no connector) + one edge from it
    - one connector-ingested episode + one edge from it, with ACL
      allowing only alice (by Google sub).

    Returns a dict with all the IDs callers need.
    """
    ws_id = workspace["workspace_id"]
    alice_user_id = workspace["user_id"]

    bob_user_id = str(uuid4())

    async with session_scope() as session:
        # Bob exists as an app_user.
        await session.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :email, :h, :n)"
            ),
            {"id": bob_user_id, "email": f"bob-{bob_user_id}@example.com", "h": "x", "n": "Bob"},
        )
        # Bob is a workspace editor.
        await session.execute(
            text(
                "INSERT INTO workspace_member (workspace_id, user_id, role) "
                "VALUES (CAST(:w AS uuid), CAST(:u AS uuid), 'editor')"
            ),
            {"w": ws_id, "u": bob_user_id},
        )

    async with session_scope(workspace_id=ws_id, user_id=alice_user_id) as session:
        # Connector instance.
        connector_id = str(uuid4())
        await session.execute(
            text(
                """
                INSERT INTO connector_instance (id, workspace_id, connector_kind, display_name, created_by)
                VALUES (CAST(:id AS uuid), CAST(:w AS uuid), 'google_drive', 'Test Drive', CAST(:by AS uuid))
                """
            ),
            {"id": connector_id, "w": ws_id, "by": alice_user_id},
        )

        # Two episodes: one user-asserted (no connector), one connector-ingested.
        user_ep = str(uuid4())
        conn_ep = str(uuid4())
        await session.execute(
            text(
                """
                INSERT INTO episode (id, workspace_id, source_kind, occurred_at, content)
                VALUES (CAST(:id AS uuid), CAST(:w AS uuid), 'user', now(), '{}'::jsonb)
                """
            ),
            {"id": user_ep, "w": ws_id},
        )
        await session.execute(
            text(
                """
                INSERT INTO episode (id, workspace_id, source_kind, occurred_at, content,
                                     connector_instance_id, external_id, mime_type)
                VALUES (CAST(:id AS uuid), CAST(:w AS uuid), 'episode', now(), '{}'::jsonb,
                        CAST(:c AS uuid), 'drive-file-1', 'application/vnd.google-apps.document')
                """
            ),
            {"id": conn_ep, "w": ws_id, "c": connector_id},
        )

        # ACL on the connector episode — allow Alice's Google sub.
        alice_google_sub = "google-sub-alice-123"
        alice_email = "alice@acme.com"
        await session.execute(
            text(
                """
                INSERT INTO episode_acl (episode_id, workspace_id, principal_kind, principal_external_id, role)
                VALUES (CAST(:e AS uuid), CAST(:w AS uuid), 'user', :pid, 'reader')
                """
            ),
            {"e": conn_ep, "w": ws_id, "pid": alice_google_sub},
        )

        # Alice's identity bridge.
        await session.execute(
            text(
                """
                INSERT INTO user_external_identity
                  (workspace_id, user_id, provider, external_id, external_email)
                VALUES (CAST(:w AS uuid), CAST(:u AS uuid), 'google', :ext, :email)
                """
            ),
            {"w": ws_id, "u": alice_user_id, "ext": alice_google_sub, "email": alice_email},
        )

        # Two edges: one off the user-asserted episode, one off the connector.
        # Need an entity + relation type to FK to. The fixtures create
        # alice + acme entities and seed the system ontology.
        rel_id = (
            await session.execute(
                text("SELECT id::text FROM relation_type LIMIT 1")
            )
        ).scalar_one()

        user_edge = str(uuid4())
        conn_edge = str(uuid4())
        await session.execute(
            text(
                """
                INSERT INTO edge (id, workspace_id, subject_id, predicate_id, object_id,
                                  fact, source_id, source_kind)
                VALUES (CAST(:id AS uuid), CAST(:w AS uuid),
                        CAST(:s AS uuid), CAST(:p AS uuid), CAST(:o AS uuid),
                        'user-asserted edge', CAST(:src AS uuid), 'episode')
                """
            ),
            {
                "id": user_edge, "w": ws_id,
                "s": two_people["alice"], "p": rel_id, "o": two_people["acme"],
                "src": user_ep,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO edge (id, workspace_id, subject_id, predicate_id, object_id,
                                  fact, source_id, source_kind)
                VALUES (CAST(:id AS uuid), CAST(:w AS uuid),
                        CAST(:s AS uuid), CAST(:p AS uuid), CAST(:o AS uuid),
                        'connector edge', CAST(:src AS uuid), 'episode')
                """
            ),
            {
                "id": conn_edge, "w": ws_id,
                "s": two_people["alice"], "p": rel_id, "o": two_people["acme"],
                "src": conn_ep,
            },
        )

    yield {
        "ws_id": ws_id,
        "alice_user_id": alice_user_id,
        "bob_user_id": bob_user_id,
        "user_ep": user_ep,
        "conn_ep": conn_ep,
        "user_edge": user_edge,
        "conn_edge": conn_edge,
        "alice_google_sub": alice_google_sub,
        "alice_email": alice_email,
        "connector_id": connector_id,
        "rel_id": rel_id,
        "alice_entity": two_people["alice"],
        "acme_entity": two_people["acme"],
    }


async def _visible_edges(session, principal: Principal) -> set[str]:
    clause = edge_visibility_clause(principal, edge_alias="e")
    sql = text(
        f"SELECT e.id::text FROM edge e WHERE {clause.text}"
    ).bindparams(*clause._bindparams.values()) if clause._bindparams else text(
        f"SELECT e.id::text FROM edge e WHERE {clause.text}"
    )
    rows = await session.execute(sql)
    return {r[0] for r in rows}


async def _visible_episodes(session, principal: Principal) -> set[str]:
    clause = episode_visibility_clause(principal, episode_alias="ep")
    sql = text(
        f"SELECT ep.id::text FROM episode ep WHERE {clause.text}"
    ).bindparams(*clause._bindparams.values()) if clause._bindparams else text(
        f"SELECT ep.id::text FROM episode ep WHERE {clause.text}"
    )
    rows = await session.execute(sql)
    return {r[0] for r in rows}


@pytest.mark.asyncio
async def test_service_kind_sees_all_edges(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        p = _principal(fx["alice_user_id"], fx["ws_id"], kind="service")
        visible = await _visible_edges(session, p)
        assert fx["user_edge"] in visible
        assert fx["conn_edge"] in visible


@pytest.mark.asyncio
async def test_owner_role_bypasses_acl(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        p = _principal(fx["alice_user_id"], fx["ws_id"], kind="user", role="owner")
        visible = await _visible_edges(session, p)
        assert fx["user_edge"] in visible
        assert fx["conn_edge"] in visible


@pytest.mark.asyncio
async def test_user_with_matching_identity_sees_connector_edge(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Alice has a Google identity that matches the ACL on conn_ep.
        p = _principal(fx["alice_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["user_edge"] in visible, "user-asserted edge should always be visible to members"
        assert fx["conn_edge"] in visible, "ACL match → connector edge visible"


@pytest.mark.asyncio
async def test_user_without_identity_does_not_see_connector_edge(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Bob has no user_external_identity row.
        p = _principal(fx["bob_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["user_edge"] in visible
        assert fx["conn_edge"] not in visible, "no identity bridge → connector edge hidden"


@pytest.mark.asyncio
async def test_user_visibility_via_email_match(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Add an ACL row keyed by Bob's email; give Bob an identity row
        # whose external_email matches; he should now see the connector
        # edge through the email-match branch.
        bob_email = f"bob-{fx['bob_user_id']}@example.com"
        await session.execute(
            text(
                """
                INSERT INTO episode_acl (episode_id, workspace_id, principal_kind, principal_external_id)
                VALUES (CAST(:e AS uuid), CAST(:w AS uuid), 'user', :pid)
                """
            ),
            {"e": fx["conn_ep"], "w": fx["ws_id"], "pid": bob_email},
        )
        await session.execute(
            text(
                """
                INSERT INTO user_external_identity
                  (workspace_id, user_id, provider, external_id, external_email)
                VALUES (CAST(:w AS uuid), CAST(:u AS uuid), 'google', :ext, :email)
                """
            ),
            {"w": fx["ws_id"], "u": fx["bob_user_id"], "ext": "google-sub-bob", "email": bob_email},
        )
        p = _principal(fx["bob_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["conn_edge"] in visible


@pytest.mark.asyncio
async def test_anyone_acl_entry_makes_episode_universal(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Make the connector episode shared with 'anyone'.
        await session.execute(
            text(
                """
                INSERT INTO episode_acl (episode_id, workspace_id, principal_kind, principal_external_id)
                VALUES (CAST(:e AS uuid), CAST(:w AS uuid), 'anyone', NULL)
                """
            ),
            {"e": fx["conn_ep"], "w": fx["ws_id"]},
        )
        # Bob has no identity bridge but the 'anyone' entry should still match.
        p = _principal(fx["bob_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["conn_edge"] in visible


@pytest.mark.asyncio
async def test_group_acl_resolves_via_user_groups(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Add a group ACL on the connector episode.
        await session.execute(
            text(
                """
                INSERT INTO episode_acl (episode_id, workspace_id, principal_kind, principal_external_id)
                VALUES (CAST(:e AS uuid), CAST(:w AS uuid), 'group', 'group-engineering')
                """
            ),
            {"e": fx["conn_ep"], "w": fx["ws_id"]},
        )
        # Bob is a member of group-engineering via his identity bridge.
        await session.execute(
            text(
                """
                INSERT INTO user_external_identity
                  (workspace_id, user_id, provider, external_id, external_email, groups)
                VALUES (CAST(:w AS uuid), CAST(:u AS uuid), 'google', 'sub-bob', 'bob@x.com',
                        '[{"id": "group-engineering", "name": "Engineering"}]'::jsonb)
                """
            ),
            {"w": fx["ws_id"], "u": fx["bob_user_id"]},
        )
        p = _principal(fx["bob_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["conn_edge"] in visible


@pytest.mark.asyncio
async def test_domain_acl_resolves_via_user_email(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Domain-shared with acme.com — Alice has an acme.com email.
        await session.execute(
            text(
                """
                INSERT INTO episode_acl (episode_id, workspace_id, principal_kind, principal_external_id)
                VALUES (CAST(:e AS uuid), CAST(:w AS uuid), 'domain', 'acme.com')
                """
            ),
            {"e": fx["conn_ep"], "w": fx["ws_id"]},
        )
        p = _principal(fx["alice_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["conn_edge"] in visible


@pytest.mark.asyncio
async def test_soft_deleted_episode_invisible_to_user(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        await session.execute(
            text("UPDATE episode SET deleted_at = now() WHERE id = CAST(:id AS uuid)"),
            {"id": fx["conn_ep"]},
        )
        p = _principal(fx["alice_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_edges(session, p)
        assert fx["conn_edge"] not in visible, "soft-deleted source → edge invisible"


@pytest.mark.asyncio
async def test_episode_visibility_clause_user(acl_fixture):
    fx = acl_fixture
    async with session_scope(workspace_id=fx["ws_id"], user_id=fx["alice_user_id"]) as session:
        # Alice has matching identity → sees both episodes.
        p_alice = _principal(fx["alice_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_episodes(session, p_alice)
        assert fx["user_ep"] in visible
        assert fx["conn_ep"] in visible

        # Bob has no identity → sees only the user-asserted episode.
        p_bob = _principal(fx["bob_user_id"], fx["ws_id"], kind="user", role="editor")
        visible = await _visible_episodes(session, p_bob)
        assert fx["user_ep"] in visible
        assert fx["conn_ep"] not in visible
