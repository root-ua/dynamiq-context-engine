"""Fact review queue ("propose_fact" → ``pending_fact`` table).

Facts arriving through automated extraction land in ``edge`` directly only
when their confidence meets the configured threshold. Below the threshold
they land in ``pending_fact`` for human review; well-below they are
auto-rejected (still recorded for audit). This is the RFC §15.2 contract.

Approval promotes a pending row to an ``edge`` row, reusing
``edge.add_fact`` so all cardinality-one / contradictor invariants apply
on approval just as they would on direct write.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain import edge as edge_mod
from app.domain.edge import Edge, FactWriteResult  # noqa: F401  (re-export for convenience)

log = get_logger(__name__)


# Fallback thresholds when no extraction_policy row exists for a workspace.
DEFAULT_MIN_CONFIDENCE = 0.7
DEFAULT_AUTO_REJECT_BELOW = 0.3


class ProposalError(Exception):
    pass


@dataclass
class PendingFact:
    id: str
    workspace_id: str
    subject_id: str
    predicate_id: str
    object_id: str
    fact: str
    props: dict[str, Any]
    valid_from: str
    valid_to: str | None
    source_id: str | None
    source_kind: str | None
    confidence: float
    prov_activity_id: str | None
    status: str
    reason: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    approved_edge_id: str | None
    created_at: str


@dataclass
class Thresholds:
    min_confidence: float
    auto_reject_below: float


# ---------------------------------------------------------------------------
# Threshold lookup
# ---------------------------------------------------------------------------

async def get_thresholds(
    session: AsyncSession,
    *,
    workspace_id: str,
    entity_type_id: str | None = None,
    relation_type_id: str | None = None,
) -> Thresholds:
    """Resolve the (min_confidence, auto_reject_below) thresholds.

    Precedence: relation-specific row > entity-specific row > workspace
    default row > built-in defaults. The first row found wins.
    """
    if relation_type_id is not None:
        row = (
            await session.execute(
                text(
                    """
                    SELECT min_confidence, auto_reject_below
                    FROM extraction_policy
                    WHERE workspace_id = :ws AND relation_type_id = :rt
                    """
                ),
                {"ws": workspace_id, "rt": relation_type_id},
            )
        ).mappings().first()
        if row:
            return Thresholds(row["min_confidence"], row["auto_reject_below"])

    if entity_type_id is not None:
        row = (
            await session.execute(
                text(
                    """
                    SELECT min_confidence, auto_reject_below
                    FROM extraction_policy
                    WHERE workspace_id = :ws AND entity_type_id = :et
                    """
                ),
                {"ws": workspace_id, "et": entity_type_id},
            )
        ).mappings().first()
        if row:
            return Thresholds(row["min_confidence"], row["auto_reject_below"])

    row = (
        await session.execute(
            text(
                """
                SELECT min_confidence, auto_reject_below
                FROM extraction_policy
                WHERE workspace_id = :ws
                  AND entity_type_id IS NULL AND relation_type_id IS NULL
                """
            ),
            {"ws": workspace_id},
        )
    ).mappings().first()
    if row:
        return Thresholds(row["min_confidence"], row["auto_reject_below"])

    return Thresholds(DEFAULT_MIN_CONFIDENCE, DEFAULT_AUTO_REJECT_BELOW)


async def upsert_policy(
    session: AsyncSession,
    *,
    workspace_id: str,
    entity_type_id: str | None = None,
    relation_type_id: str | None = None,
    min_confidence: float,
    auto_reject_below: float,
) -> str:
    """Insert or update a single extraction_policy row.

    Pass `entity_type_id=None and relation_type_id=None` to set/replace
    the workspace default row.
    """
    if entity_type_id and relation_type_id:
        raise ProposalError("set at most one of entity_type_id / relation_type_id")
    result = await session.execute(
        text(
            """
            INSERT INTO extraction_policy (
              workspace_id, entity_type_id, relation_type_id,
              min_confidence, auto_reject_below
            ) VALUES (:ws, :et, :rt, :mc, :ar)
            ON CONFLICT (workspace_id) WHERE entity_type_id IS NULL
                                          AND relation_type_id IS NULL
              DO UPDATE SET min_confidence = EXCLUDED.min_confidence,
                            auto_reject_below = EXCLUDED.auto_reject_below
            RETURNING id::text
            """
        ),
        {
            "ws": workspace_id,
            "et": entity_type_id,
            "rt": relation_type_id,
            "mc": min_confidence,
            "ar": auto_reject_below,
        },
    )
    return result.scalar_one()


async def list_policies(
    session: AsyncSession, *, workspace_id: str
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id::text,
                       entity_type_id::text  AS entity_type_id,
                       relation_type_id::text AS relation_type_id,
                       min_confidence, auto_reject_below,
                       created_at::text, updated_at::text
                FROM extraction_policy
                WHERE workspace_id = :ws
                ORDER BY entity_type_id NULLS LAST, relation_type_id NULLS LAST
                """
            ),
            {"ws": workspace_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def delete_policy(session: AsyncSession, *, policy_id: str) -> bool:
    result = await session.execute(
        text("DELETE FROM extraction_policy WHERE id = :id"),
        {"id": policy_id},
    )
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Pending-fact lifecycle
# ---------------------------------------------------------------------------

async def enqueue_pending_fact(
    session: AsyncSession,
    *,
    workspace_id: str,
    subject_id: str,
    predicate_id: str,
    object_id: str,
    fact: str,
    confidence: float,
    status: str = "pending",
    reason: str | None = None,
    props: dict[str, Any] | None = None,
    valid_from: Any = None,
    valid_to: Any = None,
    source_id: str | None = None,
    source_kind: str | None = None,
    prov_activity_id: str | None = None,
) -> str:
    """Insert a row into ``pending_fact``. Returns the new id."""
    import json as _json

    result = await session.execute(
        text(
            """
            INSERT INTO pending_fact (
              workspace_id, subject_id, predicate_id, object_id,
              fact, props, valid_from, valid_to,
              source_id, source_kind, confidence,
              prov_activity_id, status, reason
            ) VALUES (
              :workspace_id, :subject_id, :predicate_id, :object_id,
              :fact, CAST(:props AS jsonb),
              COALESCE(CAST(:vt_from AS timestamptz), now()),
              CAST(:vt_to AS timestamptz),
              :source_id, :source_kind, :confidence,
              :prov_activity_id, :status, :reason
            )
            RETURNING id::text
            """
        ),
        {
            "workspace_id": workspace_id,
            "subject_id": subject_id,
            "predicate_id": predicate_id,
            "object_id": object_id,
            "fact": fact,
            "props": _json.dumps(props or {}),
            "vt_from": valid_from,
            "vt_to": valid_to,
            "source_id": source_id,
            "source_kind": source_kind,
            "confidence": confidence,
            "prov_activity_id": prov_activity_id,
            "status": status,
            "reason": reason,
        },
    )
    return result.scalar_one()


async def list_proposals(
    session: AsyncSession,
    *,
    workspace_id: str,
    status: str = "pending",
    limit: int = 50,
    offset: int = 0,
    predicate_id: str | None = None,
    source_kind: str | None = None,
) -> list[PendingFact]:
    """List pending_fact rows for the review UI / MCP tool."""
    where: list[str] = ["pf.workspace_id = :ws", "pf.status = :status"]
    params: dict[str, Any] = {"ws": workspace_id, "status": status, "limit": limit, "offset": offset}
    if predicate_id:
        where.append("pf.predicate_id = :pred")
        params["pred"] = predicate_id
    if source_kind:
        where.append("pf.source_kind = :src_kind")
        params["src_kind"] = source_kind

    sql = f"""
        SELECT
          pf.id::text, pf.workspace_id::text,
          pf.subject_id::text, pf.predicate_id::text, pf.object_id::text,
          pf.fact, pf.props,
          pf.valid_from::text AS valid_from,
          pf.valid_to::text   AS valid_to,
          pf.source_id::text, pf.source_kind, pf.confidence,
          pf.prov_activity_id::text, pf.status, pf.reason,
          pf.reviewed_by::text, pf.reviewed_at::text,
          pf.approved_edge_id::text,
          pf.created_at::text
        FROM pending_fact pf
        WHERE {' AND '.join(where)}
        ORDER BY pf.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = (await session.execute(text(sql), params)).mappings().all()
    return [_row_to_pending(r) for r in rows]


async def get_proposal(
    session: AsyncSession, proposal_id: str
) -> PendingFact | None:
    row = (
        await session.execute(
            text(
                """
                SELECT
                  pf.id::text, pf.workspace_id::text,
                  pf.subject_id::text, pf.predicate_id::text, pf.object_id::text,
                  pf.fact, pf.props,
                  pf.valid_from::text AS valid_from,
                  pf.valid_to::text   AS valid_to,
                  pf.source_id::text, pf.source_kind, pf.confidence,
                  pf.prov_activity_id::text, pf.status, pf.reason,
                  pf.reviewed_by::text, pf.reviewed_at::text,
                  pf.approved_edge_id::text,
                  pf.created_at::text
                FROM pending_fact pf
                WHERE pf.id = :id
                """
            ),
            {"id": proposal_id},
        )
    ).mappings().first()
    return _row_to_pending(row) if row else None


async def approve_proposal(
    session: AsyncSession,
    *,
    proposal_id: str,
    principal_user_id: str | None,
    comment: str | None = None,
) -> Edge:
    """Promote a ``pending_fact`` row to a live ``edge``.

    Reuses :func:`edge.add_fact` so cardinality-one closures and the
    contradictor still fire on approval.
    """
    proposal = await get_proposal(session, proposal_id)
    if not proposal:
        raise ProposalError(f"proposal not found: {proposal_id}")
    if proposal.status != "pending":
        raise ProposalError(
            f"proposal not in pending state (current: {proposal.status})"
        )

    # If the source episode was deleted between proposal creation and
    # approval, refuse to write through. Materialising an edge with a
    # dangling ``source_id`` quietly breaks the provenance chain — better
    # to fail loudly so the reviewer goes back to the audit log.
    # Fire on any non-null source_id (including legacy rows that
    # forgot to set source_kind) so we don't silently leak.
    if proposal.source_id is not None and (
        proposal.source_kind is None or proposal.source_kind == "episode"
    ):
        ep_row = (
            await session.execute(
                text(
                    "SELECT 1 FROM episode "
                    "WHERE id = :id AND deleted_at IS NULL"
                ),
                {"id": proposal.source_id},
            )
        ).first()
        if ep_row is None:
            raise ProposalError(
                f"source_episode_missing: {proposal.source_id}"
            )

    # Open a fresh approval activity to attribute the resulting edge to
    # the reviewing user — the original extraction activity stays on
    # ``edge.prov_activity_id`` only if no user supersedes it.
    from app.domain import provenance as prov

    approval_activity = await prov.start_activity(
        session,
        workspace_id=proposal.workspace_id,
        kind="approval",
        agent_kind="user",
        agent_ref=principal_user_id,
        inputs={"proposal_id": proposal_id, "comment": comment},
    )

    approved_edge = await edge_mod.add_fact(
        session,
        workspace_id=proposal.workspace_id,
        subject_id=proposal.subject_id,
        predicate=proposal.predicate_id,
        object_id=proposal.object_id,
        fact=proposal.fact,
        props=proposal.props,
        valid_from=_to_datetime(proposal.valid_from),
        valid_to=_to_datetime(proposal.valid_to),
        source_id=proposal.source_id,
        source_kind=proposal.source_kind,
        confidence=proposal.confidence,
        created_by=principal_user_id,
        prov_activity_id=approval_activity,
    )

    await session.execute(
        text(
            """
            UPDATE pending_fact
            SET status = 'approved',
                reviewed_by = :user_id,
                reviewed_at = now(),
                approved_edge_id = :edge_id,
                reason = COALESCE(:comment, reason)
            WHERE id = :id
            """
        ),
        {
            "id": proposal_id,
            "user_id": principal_user_id,
            "edge_id": approved_edge.id,
            "comment": comment,
        },
    )

    await prov.end_activity(
        session, approval_activity, outputs={"edge_id": approved_edge.id}
    )

    await session.execute(
        text(
            """
            INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                   target_kind, target_id, diff)
            VALUES (:ws, 'user', :user_id, 'proposal.approve',
                    'pending_fact', :id,
                    jsonb_build_object('approved_edge_id', CAST(:edge_id AS text)))
            """
        ),
        {
            "ws": proposal.workspace_id,
            "user_id": principal_user_id,
            "id": proposal_id,
            "edge_id": approved_edge.id,
        },
    )

    return approved_edge


async def reject_proposal(
    session: AsyncSession,
    *,
    proposal_id: str,
    principal_user_id: str | None,
    reason: str,
) -> PendingFact:
    proposal = await get_proposal(session, proposal_id)
    if not proposal:
        raise ProposalError(f"proposal not found: {proposal_id}")
    if proposal.status != "pending":
        raise ProposalError(
            f"proposal not in pending state (current: {proposal.status})"
        )

    await session.execute(
        text(
            """
            UPDATE pending_fact
            SET status = 'rejected',
                reviewed_by = :user_id,
                reviewed_at = now(),
                reason = :reason
            WHERE id = :id
            """
        ),
        {
            "id": proposal_id,
            "user_id": principal_user_id,
            "reason": reason,
        },
    )

    await session.execute(
        text(
            """
            INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                   target_kind, target_id, diff)
            VALUES (:ws, 'user', :user_id, 'proposal.reject',
                    'pending_fact', :id,
                    jsonb_build_object('reason', CAST(:reason AS text)))
            """
        ),
        {
            "ws": proposal.workspace_id,
            "user_id": principal_user_id,
            "id": proposal_id,
            "reason": reason,
        },
    )

    updated = await get_proposal(session, proposal_id)
    assert updated is not None
    return updated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_pending(row: Any) -> PendingFact:
    return PendingFact(
        id=row["id"],
        workspace_id=row["workspace_id"],
        subject_id=row["subject_id"],
        predicate_id=row["predicate_id"],
        object_id=row["object_id"],
        fact=row["fact"],
        props=row.get("props") or {},
        valid_from=row["valid_from"],
        valid_to=row.get("valid_to"),
        source_id=row.get("source_id"),
        source_kind=row.get("source_kind"),
        confidence=row["confidence"],
        prov_activity_id=row.get("prov_activity_id"),
        status=row["status"],
        reason=row.get("reason"),
        reviewed_by=row.get("reviewed_by"),
        reviewed_at=row.get("reviewed_at"),
        approved_edge_id=row.get("approved_edge_id"),
        created_at=row["created_at"],
    )


def _to_datetime(s: str | None):
    from datetime import datetime
    if not s:
        return None
    # Postgres timestamptz comes back as 'YYYY-MM-DD HH:MM:SS.ffffff+00'
    # — fromisoformat handles a 'T' separator natively; convert space.
    return datetime.fromisoformat(s.replace(" ", "T"))
