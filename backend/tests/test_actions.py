"""Kinetic action layer — register, invoke, idempotency, approval flow."""
from __future__ import annotations

import pytest

from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import action as action_mod
from app.domain import edge as edge_mod


def _user_principal(workspace_id: str, user_id: str, role: str = "owner") -> Principal:
    return Principal(
        user_id=user_id,
        email="t@example.com",
        workspace_id=workspace_id,
        role=role,
        claims={},
        kind="user",
    )


@pytest.mark.asyncio
async def test_register_and_list_action_types(workspace):
    ws_id = workspace["workspace_id"]
    user_id = workspace["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await action_mod.ensure_builtin_actions(session, workspace_id=ws_id)
        types = await action_mod.list_action_types(session, workspace_id=ws_id)
    slugs = sorted(t.slug for t in types)
    assert "attach_evidence_to_fact" in slugs


@pytest.mark.asyncio
async def test_attach_evidence_to_fact(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    principal = _user_principal(ws_id, user_id)

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await action_mod.ensure_builtin_actions(session, workspace_id=ws_id)
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

        inv = await action_mod.execute_action(
            session,
            workspace_id=ws_id,
            type_slug="attach_evidence_to_fact",
            input={"edge_id": edge.id, "comment": "Verified by Slack thread"},
            idempotency_key="key-1",
            principal=principal,
        )

        assert inv.status == "completed"
        assert inv.result is not None
        assert inv.result["edge_id"] == edge.id
        assert inv.prov_activity_id is not None

        # Re-invocation with same key returns the cached row, no new write.
        inv2 = await action_mod.execute_action(
            session,
            workspace_id=ws_id,
            type_slug="attach_evidence_to_fact",
            input={"edge_id": edge.id, "comment": "Different comment ignored"},
            idempotency_key="key-1",
            principal=principal,
        )
        assert inv2.id == inv.id

        # Verify evidence was appended to props.
        from sqlalchemy import text as _t
        row = (
            await session.execute(
                _t("SELECT props FROM edge WHERE id = :id"), {"id": edge.id}
            )
        ).first()
        props = row[0]
        assert "evidence" in props
        assert len(props["evidence"]) == 1
        assert props["evidence"][0]["comment"] == "Verified by Slack thread"


@pytest.mark.asyncio
async def test_input_schema_validation_blocks_bad_input(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    principal = _user_principal(ws_id, user_id)

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await action_mod.ensure_builtin_actions(session, workspace_id=ws_id)
        with pytest.raises(action_mod.ActionError):
            await action_mod.execute_action(
                session,
                workspace_id=ws_id,
                type_slug="attach_evidence_to_fact",
                input={},  # missing edge_id
                idempotency_key="bad-1",
                principal=principal,
            )


@pytest.mark.asyncio
async def test_role_gate(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    viewer = _user_principal(ws_id, user_id, role="viewer")

    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await action_mod.register_action_type(
            session,
            workspace_id=ws_id,
            slug="admin_only",
            name="Admin Only",
            input_schema={"type": "object"},
            required_role="admin",
        )

        with pytest.raises(action_mod.ActionError):
            await action_mod.execute_action(
                session,
                workspace_id=ws_id,
                type_slug="admin_only",
                input={},
                idempotency_key="x",
                principal=viewer,
            )
