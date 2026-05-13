"""Kinetic action layer — typed write-back operations (RFC-001 §19).

Action types are registered through ``register_action_type`` (DB row) and
their handlers through ``register_handler`` (Python coroutine).
``execute_action`` dispatches by slug after validating the input against
the type's JSON Schema, gating on workspace role, and writing a
``prov_activity`` row to attribute the call.

Idempotency: ``(workspace_id, action_type_id, idempotency_key)`` is
UNIQUE. A re-invocation with the same key returns the cached result
without running side effects.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import jsonschema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import Principal
from app.core.logging import get_logger
from app.domain import provenance as prov_mod

log = get_logger(__name__)


class ActionError(Exception):
    pass


@dataclass
class ActionType:
    id: str
    workspace_id: str
    slug: str
    name: str
    description: str | None
    source_kind: str | None
    input_schema: dict[str, Any]
    required_role: str
    idempotency_required: bool
    requires_approval: bool
    side_effects: list[str]
    enabled: bool


@dataclass
class ActionInvocation:
    id: str
    workspace_id: str
    action_type_id: str
    action_type_slug: str
    principal_user_id: str | None
    idempotency_key: str
    input: dict[str, Any]
    status: str  # 'pending' | 'approved' | 'executing' | 'completed' | 'failed' | 'rejected'
    result: dict[str, Any] | None
    error_message: str | None
    prov_activity_id: str | None
    emitted_edge_id: str | None
    started_at: str
    completed_at: str | None


# ---------------------------------------------------------------------------
# Handler registry — process-local, populated at import time
# ---------------------------------------------------------------------------

HandlerSig = Callable[
    [AsyncSession, dict[str, Any], ActionInvocation, Principal | None],
    Awaitable[dict[str, Any]],
]
_HANDLERS: dict[str, HandlerSig] = {}


def register_handler(slug: str) -> Callable[[HandlerSig], HandlerSig]:
    def deco(fn: HandlerSig) -> HandlerSig:
        _HANDLERS[slug] = fn
        return fn
    return deco


def get_handler(slug: str) -> HandlerSig | None:
    return _HANDLERS.get(slug)


# ---------------------------------------------------------------------------
# Action-type CRUD
# ---------------------------------------------------------------------------

async def register_action_type(
    session: AsyncSession,
    *,
    workspace_id: str,
    slug: str,
    name: str,
    input_schema: dict[str, Any],
    description: str | None = None,
    source_kind: str | None = None,
    required_role: str = "editor",
    idempotency_required: bool = True,
    requires_approval: bool = False,
    side_effects: list[str] | None = None,
    enabled: bool = True,
) -> ActionType:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO action_type (
                  workspace_id, slug, name, description, source_kind,
                  input_schema, required_role, idempotency_required,
                  requires_approval, side_effects, enabled
                ) VALUES (
                  :ws, :slug, :name, :desc, :sk,
                  CAST(:is AS jsonb), :role, :idr, :ra,
                  CAST(:se AS jsonb), :en
                )
                ON CONFLICT (workspace_id, slug) DO UPDATE SET
                  name = EXCLUDED.name,
                  description = EXCLUDED.description,
                  source_kind = EXCLUDED.source_kind,
                  input_schema = EXCLUDED.input_schema,
                  required_role = EXCLUDED.required_role,
                  idempotency_required = EXCLUDED.idempotency_required,
                  requires_approval = EXCLUDED.requires_approval,
                  side_effects = EXCLUDED.side_effects,
                  enabled = EXCLUDED.enabled
                RETURNING id::text, workspace_id::text, slug, name, description,
                          source_kind, input_schema, required_role,
                          idempotency_required, requires_approval,
                          side_effects, enabled
                """
            ),
            {
                "ws": workspace_id, "slug": slug, "name": name, "desc": description,
                "sk": source_kind, "is": json.dumps(input_schema),
                "role": required_role, "idr": idempotency_required,
                "ra": requires_approval,
                "se": json.dumps(side_effects or []), "en": enabled,
            },
        )
    ).mappings().first()
    assert row is not None
    return _row_to_action_type(row)


async def list_action_types(
    session: AsyncSession, *, workspace_id: str
) -> list[ActionType]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, slug, name, description,
                       source_kind, input_schema, required_role,
                       idempotency_required, requires_approval,
                       side_effects, enabled
                FROM action_type
                WHERE workspace_id = :ws
                ORDER BY name
                """
            ),
            {"ws": workspace_id},
        )
    ).mappings().all()
    return [_row_to_action_type(r) for r in rows]


async def get_action_type(
    session: AsyncSession, *, workspace_id: str, slug: str
) -> ActionType | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, slug, name, description,
                       source_kind, input_schema, required_role,
                       idempotency_required, requires_approval,
                       side_effects, enabled
                FROM action_type
                WHERE workspace_id = :ws AND slug = :slug
                """
            ),
            {"ws": workspace_id, "slug": slug},
        )
    ).mappings().first()
    return _row_to_action_type(row) if row else None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

_ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}


def _role_satisfies(have: str | None, want: str) -> bool:
    return _ROLE_ORDER.get(have or "viewer", -1) >= _ROLE_ORDER[want]


async def execute_action(
    session: AsyncSession,
    *,
    workspace_id: str,
    type_slug: str,
    input: dict[str, Any],
    idempotency_key: str,
    principal: Principal,
) -> ActionInvocation:
    action = await get_action_type(
        session, workspace_id=workspace_id, slug=type_slug
    )
    if not action:
        raise ActionError(f"action type not found: {type_slug}")
    if not action.enabled:
        raise ActionError(f"action type disabled: {type_slug}")

    if not _role_satisfies(principal.role, action.required_role):
        raise ActionError(
            f"insufficient role: have={principal.role!r} need={action.required_role!r}"
        )

    # Idempotency check FIRST — re-invocation with the same key is a no-op.
    cached = (
        await session.execute(
            text(
                """
                SELECT id::text FROM action_invocation
                WHERE workspace_id = :ws
                  AND action_type_id = :at
                  AND idempotency_key = :ik
                """
            ),
            {"ws": workspace_id, "at": action.id, "ik": idempotency_key},
        )
    ).first()
    if cached:
        existing = await get_invocation(session, cached[0])
        assert existing is not None
        return existing

    # Validate input.
    try:
        jsonschema.validate(input, action.input_schema)
    except jsonschema.ValidationError as exc:
        raise ActionError(f"input invalid: {exc.message}") from exc

    activity_id = await prov_mod.start_activity(
        session,
        workspace_id=workspace_id,
        kind="action",
        agent_kind="user" if principal.kind == "user" else "system",
        agent_ref=principal.user_id,
        inputs={"action_slug": type_slug, "idempotency_key": idempotency_key},
    )

    status = "pending" if action.requires_approval else "executing"
    row = (
        await session.execute(
            text(
                """
                INSERT INTO action_invocation (
                  workspace_id, action_type_id, principal_user_id,
                  idempotency_key, input, status, prov_activity_id
                ) VALUES (
                  :ws, :at, :pu, :ik, CAST(:in AS jsonb), :st, :pa
                )
                RETURNING id::text
                """
            ),
            {
                "ws": workspace_id, "at": action.id, "pu": principal.user_id,
                "ik": idempotency_key, "in": json.dumps(input), "st": status,
                "pa": activity_id,
            },
        )
    ).first()
    invocation_id = row[0]

    if action.requires_approval:
        # Caller polls / receives a webhook later; the actual handler runs
        # only after the invocation is approved.
        result = await get_invocation(session, invocation_id)
        assert result is not None
        return result

    # Dispatch handler in-line (caller can defer to Arq if needed).
    return await _run_handler(
        session,
        invocation_id=invocation_id,
        action=action,
        input=input,
        activity_id=activity_id,
        principal=principal,
    )


async def approve_invocation(
    session: AsyncSession,
    *,
    invocation_id: str,
    principal: Principal,
) -> ActionInvocation:
    inv = await get_invocation(session, invocation_id)
    if not inv:
        raise ActionError(f"invocation not found: {invocation_id}")
    if inv.status != "pending":
        raise ActionError(f"invocation not pending (current: {inv.status})")
    action = await get_action_type_by_id(session, inv.action_type_id)
    if not action:
        raise ActionError("action type missing")
    if not _role_satisfies(principal.role, "admin"):
        raise ActionError("admin or owner required to approve")

    await session.execute(
        text("UPDATE action_invocation SET status = 'executing' WHERE id = :id"),
        {"id": invocation_id},
    )
    return await _run_handler(
        session,
        invocation_id=invocation_id,
        action=action,
        input=inv.input,
        activity_id=inv.prov_activity_id,
        principal=principal,
    )


async def reject_invocation(
    session: AsyncSession,
    *,
    invocation_id: str,
    principal: Principal,
    reason: str,
) -> ActionInvocation:
    inv = await get_invocation(session, invocation_id)
    if not inv:
        raise ActionError(f"invocation not found: {invocation_id}")
    if inv.status != "pending":
        raise ActionError(f"invocation not pending (current: {inv.status})")

    await session.execute(
        text(
            """
            UPDATE action_invocation
            SET status = 'rejected',
                error_message = :reason,
                completed_at = now()
            WHERE id = :id
            """
        ),
        {"id": invocation_id, "reason": reason},
    )
    if inv.prov_activity_id:
        await prov_mod.end_activity(
            session, inv.prov_activity_id,
            outputs={"rejected": True, "reason": reason},
        )
    updated = await get_invocation(session, invocation_id)
    assert updated is not None
    return updated


async def list_invocations(
    session: AsyncSession,
    *,
    workspace_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ActionInvocation]:
    where = ["ai.workspace_id = :ws"]
    params: dict[str, Any] = {"ws": workspace_id, "limit": limit, "offset": offset}
    if status:
        where.append("ai.status = :st")
        params["st"] = status
    rows = (
        await session.execute(
            text(
                f"""
                SELECT ai.id::text, ai.workspace_id::text,
                       ai.action_type_id::text, at.slug AS action_type_slug,
                       ai.principal_user_id::text, ai.idempotency_key,
                       ai.input, ai.status, ai.result, ai.error_message,
                       ai.prov_activity_id::text, ai.emitted_edge_id::text,
                       ai.started_at::text, ai.completed_at::text
                FROM action_invocation ai
                JOIN action_type at ON at.id = ai.action_type_id
                WHERE {' AND '.join(where)}
                ORDER BY ai.started_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).mappings().all()
    return [_row_to_invocation(r) for r in rows]


async def get_invocation(
    session: AsyncSession, invocation_id: str
) -> ActionInvocation | None:
    row = (
        await session.execute(
            text(
                """
                SELECT ai.id::text, ai.workspace_id::text,
                       ai.action_type_id::text, at.slug AS action_type_slug,
                       ai.principal_user_id::text, ai.idempotency_key,
                       ai.input, ai.status, ai.result, ai.error_message,
                       ai.prov_activity_id::text, ai.emitted_edge_id::text,
                       ai.started_at::text, ai.completed_at::text
                FROM action_invocation ai
                JOIN action_type at ON at.id = ai.action_type_id
                WHERE ai.id = :id
                """
            ),
            {"id": invocation_id},
        )
    ).mappings().first()
    return _row_to_invocation(row) if row else None


async def get_action_type_by_id(
    session: AsyncSession, action_type_id: str
) -> ActionType | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, slug, name, description,
                       source_kind, input_schema, required_role,
                       idempotency_required, requires_approval,
                       side_effects, enabled
                FROM action_type WHERE id = :id
                """
            ),
            {"id": action_type_id},
        )
    ).mappings().first()
    return _row_to_action_type(row) if row else None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

async def _run_handler(
    session: AsyncSession,
    *,
    invocation_id: str,
    action: ActionType,
    input: dict[str, Any],
    activity_id: str | None,
    principal: Principal,
) -> ActionInvocation:
    handler = get_handler(action.slug)
    if not handler:
        await session.execute(
            text(
                """
                UPDATE action_invocation
                SET status = 'failed',
                    error_message = :err,
                    completed_at = now()
                WHERE id = :id
                """
            ),
            {"id": invocation_id, "err": f"no handler registered for {action.slug}"},
        )
        if activity_id:
            await prov_mod.end_activity(
                session, activity_id, outputs={"error": "no_handler"}
            )
        result = await get_invocation(session, invocation_id)
        assert result is not None
        return result

    inv = await get_invocation(session, invocation_id)
    assert inv is not None

    try:
        result = await handler(session, input, inv, principal)
    except Exception as exc:
        log.exception("action.handler_failed", slug=action.slug)
        await session.execute(
            text(
                """
                UPDATE action_invocation
                SET status = 'failed',
                    error_message = :err,
                    completed_at = now()
                WHERE id = :id
                """
            ),
            {"id": invocation_id, "err": str(exc)},
        )
        if activity_id:
            await prov_mod.end_activity(
                session, activity_id, outputs={"error": str(exc)}
            )
        updated = await get_invocation(session, invocation_id)
        assert updated is not None
        return updated

    await session.execute(
        text(
            """
            UPDATE action_invocation
            SET status = 'completed',
                result = CAST(:res AS jsonb),
                emitted_edge_id = CAST(:eid AS uuid),
                completed_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": invocation_id,
            "res": json.dumps(result),
            "eid": result.get("emitted_edge_id"),
        },
    )
    if activity_id:
        await prov_mod.end_activity(session, activity_id, outputs=result)
    final = await get_invocation(session, invocation_id)
    assert final is not None
    return final


def _row_to_action_type(row: Any) -> ActionType:
    return ActionType(
        id=row["id"],
        workspace_id=row["workspace_id"],
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        source_kind=row.get("source_kind"),
        input_schema=row["input_schema"] or {},
        required_role=row["required_role"],
        idempotency_required=bool(row["idempotency_required"]),
        requires_approval=bool(row["requires_approval"]),
        side_effects=list(row["side_effects"] or []),
        enabled=bool(row["enabled"]),
    )


def _row_to_invocation(row: Any) -> ActionInvocation:
    return ActionInvocation(
        id=row["id"],
        workspace_id=row["workspace_id"],
        action_type_id=row["action_type_id"],
        action_type_slug=row["action_type_slug"],
        principal_user_id=row.get("principal_user_id"),
        idempotency_key=row["idempotency_key"],
        input=row["input"] or {},
        status=row["status"],
        result=row.get("result"),
        error_message=row.get("error_message"),
        prov_activity_id=row.get("prov_activity_id"),
        emitted_edge_id=row.get("emitted_edge_id"),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
    )


# ---------------------------------------------------------------------------
# Built-in actions
# ---------------------------------------------------------------------------

@register_handler("attach_evidence_to_fact")
async def _attach_evidence_to_fact(
    session: AsyncSession,
    input: dict[str, Any],
    invocation: ActionInvocation,
    principal: Principal | None,
) -> dict[str, Any]:
    """Append an evidence record to ``edge.props.evidence``."""
    edge_id = input["edge_id"]
    episode_id = input.get("episode_id")
    comment = input.get("comment", "")

    # Append evidence to edge.props.evidence (idempotent append; same
    # episode_id may appear multiple times if explicitly re-attached).
    await session.execute(
        text(
            """
            UPDATE edge
            SET props = jsonb_set(
              COALESCE(props, '{}'::jsonb),
              '{evidence}',
              COALESCE(props->'evidence', '[]'::jsonb) || jsonb_build_array(
                jsonb_build_object(
                  'episode_id', CAST(:ep AS text),
                  'comment', CAST(:c AS text),
                  'attached_at', to_jsonb(now()::text),
                  'attached_by', CAST(:ab AS text)
                )
              )
            )
            WHERE id = :eid
            """
        ),
        {
            "eid": edge_id, "ep": episode_id, "c": comment,
            "ab": principal.user_id if principal else None,
        },
    )

    await session.execute(
        text(
            """
            INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                   target_kind, target_id, diff)
            VALUES (:ws, 'user', :user_id, 'action.attach_evidence_to_fact',
                    'edge', :eid,
                    jsonb_build_object('episode_id', CAST(:ep AS text), 'comment', CAST(:c AS text)))
            """
        ),
        {
            "ws": invocation.workspace_id,
            "user_id": principal.user_id if principal else None,
            "eid": edge_id, "ep": episode_id, "c": comment,
        },
    )

    # P2 — record a derivation link from the action's activity to the
    # edge's original activity so ``get_provenance(edge_id)`` walks back
    # through the action as ``wasDerivedFrom``. Without this, the
    # action's mutation is only discoverable via the audit log.
    upstream = (
        await session.execute(
            text(
                "SELECT prov_activity_id::text FROM edge WHERE id = :id"
            ),
            {"id": edge_id},
        )
    ).scalar_one_or_none()
    if upstream and invocation.prov_activity_id:
        from app.domain import provenance as _prov

        try:
            await _prov.link_derivation(
                session,
                workspace_id=invocation.workspace_id,
                derived_activity_id=invocation.prov_activity_id,
                upstream_activity_id=upstream,
                kind="revised",
            )
        except Exception as exc:
            log.warning(
                "action.derivation_link_failed",
                edge_id=edge_id, error=str(exc),
            )

    return {
        "edge_id": edge_id,
        "episode_id": episode_id,
    }


ATTACH_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "edge_id": {"type": "string", "format": "uuid"},
        "episode_id": {"type": ["string", "null"], "format": "uuid"},
        "comment": {"type": "string", "maxLength": 2000},
    },
    "required": ["edge_id"],
    "additionalProperties": False,
}


async def ensure_builtin_actions(
    session: AsyncSession, *, workspace_id: str
) -> None:
    """Seed the built-in action types in this workspace if absent."""
    await register_action_type(
        session,
        workspace_id=workspace_id,
        slug="attach_evidence_to_fact",
        name="Attach evidence to fact",
        description=(
            "Add an evidence record (linking to an episode + optional "
            "comment) onto an existing edge. Optionally pushes a comment "
            "back to the source Drive file."
        ),
        input_schema=ATTACH_EVIDENCE_SCHEMA,
        required_role="editor",
        idempotency_required=True,
        requires_approval=False,
        side_effects=["edge_props_append", "audit_log", "source_writeback"],
    )
