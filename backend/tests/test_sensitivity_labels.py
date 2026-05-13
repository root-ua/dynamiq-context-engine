"""Sensitivity labels — CRUD, assignment, and policy evaluation."""
from __future__ import annotations

import pytest

from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import sensitivity as sens_mod


def _principal(role: str, *, kind: str = "user", user_id: str = "u") -> Principal:
    return Principal(
        user_id=user_id,
        email=f"{role}@example.com",
        workspace_id=None,
        role=role,
        claims={},
        kind=kind,
    )


@pytest.mark.asyncio
async def test_create_and_list_labels(workspace):
    ws_id = workspace["workspace_id"]
    user_id = workspace["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await sens_mod.create_label(
            session, workspace_id=ws_id, slug="pii", name="PII",
            description="Personally identifiable information",
        )
        await sens_mod.create_label(
            session, workspace_id=ws_id, slug="public", name="Public",
        )
        labels = await sens_mod.list_labels(session, workspace_id=ws_id)
    slugs = sorted(l.slug for l in labels)
    assert slugs == ["pii", "public"]


@pytest.mark.asyncio
async def test_label_hierarchy(workspace):
    """Parent labels create ltree paths like ``parent.child``."""
    ws_id = workspace["workspace_id"]
    user_id = workspace["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        parent = await sens_mod.create_label(
            session, workspace_id=ws_id, slug="confidential", name="Confidential"
        )
        child = await sens_mod.create_label(
            session, workspace_id=ws_id, slug="confidential_finance",
            name="Confidential — Finance", parent_slug="confidential",
        )
    assert parent.path == "confidential"
    assert child.path == "confidential.confidential_finance"


@pytest.mark.asyncio
async def test_mutually_exclusive_policy_drops_candidate(two_people):
    """Two conflicting labels on the same edge cause it to be dropped."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        # Set up labels + policy.
        await sens_mod.create_label(session, workspace_id=ws_id, slug="pii", name="PII")
        await sens_mod.create_label(session, workspace_id=ws_id, slug="public", name="Public")
        await sens_mod.create_policy(
            session,
            workspace_id=ws_id,
            name="no-pii-with-public",
            rule={"kind": "mutually_exclusive", "labels": ["pii", "public"]},
            action="drop",
        )

        # Create an edge and label it with both incompatible labels.
        from app.domain import edge as edge_mod
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            embed=False,
            run_contradictor=False,
        )
        await sens_mod.assign_label(
            session, workspace_id=ws_id, target_kind="edge",
            target_id=edge.id, label_slug="pii",
        )
        await sens_mod.assign_label(
            session, workspace_id=ws_id, target_kind="edge",
            target_id=edge.id, label_slug="public",
        )

        kept, summary = await sens_mod.apply_label_policy(
            session,
            workspace_id=ws_id,
            candidates=[{"kind": "edge", "id": edge.id}],
            principal=None,
        )

    assert kept == []
    assert summary["dropped"] == 1
    assert "no-pii-with-public" in summary["policies"]


@pytest.mark.asyncio
async def test_policy_skipped_when_only_one_label(two_people):
    """A single label from a mutually-exclusive set keeps the candidate."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await sens_mod.create_label(session, workspace_id=ws_id, slug="pii", name="PII")
        await sens_mod.create_label(session, workspace_id=ws_id, slug="public", name="Public")
        await sens_mod.create_policy(
            session,
            workspace_id=ws_id,
            name="no-pii-with-public",
            rule={"kind": "mutually_exclusive", "labels": ["pii", "public"]},
            action="drop",
        )

        from app.domain import edge as edge_mod
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            embed=False,
            run_contradictor=False,
        )
        await sens_mod.assign_label(
            session, workspace_id=ws_id, target_kind="edge",
            target_id=edge.id, label_slug="pii",
        )

        kept, summary = await sens_mod.apply_label_policy(
            session,
            workspace_id=ws_id,
            candidates=[{"kind": "edge", "id": edge.id}],
            principal=None,
        )

    assert len(kept) == 1
    assert summary["dropped"] == 0


@pytest.mark.asyncio
async def test_admin_owner_service_bypass_label_policy(two_people):
    """J3 — admin/owner/service principals must bypass label policies.

    The visibility ACL (``edge_visibility_clause``) bypasses for these
    principals; label policies must do the same or the two governance
    layers contradict each other and "make me admin" stops unlocking
    things consistently.
    """
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await sens_mod.create_label(session, workspace_id=ws_id, slug="pii", name="PII")
        await sens_mod.create_label(session, workspace_id=ws_id, slug="public", name="Public")
        await sens_mod.create_policy(
            session,
            workspace_id=ws_id,
            name="no-pii-with-public",
            rule={"kind": "mutually_exclusive", "labels": ["pii", "public"]},
            action="drop",
        )

        from app.domain import edge as edge_mod
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=two_people["alice"],
            predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            embed=False,
            run_contradictor=False,
        )
        for slug in ("pii", "public"):
            await sens_mod.assign_label(
                session, workspace_id=ws_id, target_kind="edge",
                target_id=edge.id, label_slug=slug,
            )

        candidates = [{"kind": "edge", "id": edge.id}]

        # Viewer / editor → filtered.
        for role in ("viewer", "editor"):
            kept, summary = await sens_mod.apply_label_policy(
                session,
                workspace_id=ws_id,
                candidates=[dict(c) for c in candidates],
                principal=_principal(role),
            )
            assert kept == [], f"{role} should be filtered"
            assert summary["dropped"] == 1

        # Admin / owner / service → bypass.
        for principal in (
            _principal("admin"),
            _principal("owner"),
            _principal("editor", kind="service"),
        ):
            kept, summary = await sens_mod.apply_label_policy(
                session,
                workspace_id=ws_id,
                candidates=[dict(c) for c in candidates],
                principal=principal,
            )
            label = (
                "admin/owner" if principal.kind == "user"
                else "service"
            )
            assert len(kept) == 1, f"{label} should bypass policy"
            assert summary["dropped"] == 0
