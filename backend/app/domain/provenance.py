"""W3C PROV-O activity tracking.

Every derived artifact (edge, entity_attribute, episode) can attribute
itself to a single ``prov_activity`` row. The activity captures *what*
produced the artifact (extraction / contradiction / manual_edit / merge /
action / seed / approval) and *who* (LLM model id, user id, etc.).

We adopt PROV-O as a vocabulary — IRIs in the JSON-LD output — without
adopting an OWL reasoner. The platform's typed property graph remains
authoritative; PROV is the wire format for "show me the provenance".

Lifecycle:

    activity_id = await start_activity(session, kind="extraction", ...)
    # ... write edges / episodes referencing prov_activity_id=activity_id
    await end_activity(session, activity_id, outputs={"edges": [...]})

Reads are workspace-scoped via the same RLS as the rest of the schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROV_CONTEXT: dict[str, Any] = {
    "@context": {
        "prov": "http://www.w3.org/ns/prov#",
        "dce": "https://dynamiq.ai/context/v1#",
        "Entity": "prov:Entity",
        "Activity": "prov:Activity",
        "Agent": "prov:Agent",
        "wasGeneratedBy": {"@id": "prov:wasGeneratedBy", "@type": "@id"},
        "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
        "wasAttributedTo": {"@id": "prov:wasAttributedTo", "@type": "@id"},
        "wasAssociatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
        "used": {"@id": "prov:used", "@type": "@id"},
        "startedAtTime": {"@id": "prov:startedAtTime", "@type": "xsd:dateTime"},
        "endedAtTime": {"@id": "prov:endedAtTime", "@type": "xsd:dateTime"},
    }
}


ActivityKind = str  # 'extraction'|'contradiction'|'manual_edit'|'merge'|'action'|'seed'|'approval'
AgentKind = str  # 'llm'|'user'|'system'


@dataclass
class Activity:
    id: str
    workspace_id: str
    kind: ActivityKind
    agent_kind: AgentKind
    agent_ref: str | None
    agent_version: str | None
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    started_at: str
    ended_at: str | None
    audit_log_id: int | None


async def start_activity(
    session: AsyncSession,
    *,
    workspace_id: str,
    kind: ActivityKind,
    agent_kind: AgentKind,
    agent_ref: str | None = None,
    agent_version: str | None = None,
    inputs: dict[str, Any] | None = None,
    audit_log_id: int | None = None,
) -> str:
    """Insert a prov_activity row in 'in-flight' state. Returns the id."""
    result = await session.execute(
        text(
            """
            INSERT INTO prov_activity (
              workspace_id, kind, agent_kind, agent_ref, agent_version,
              inputs, audit_log_id
            ) VALUES (
              :workspace_id, :kind, :agent_kind, :agent_ref, :agent_version,
              CAST(:inputs AS jsonb), :audit_log_id
            )
            RETURNING id::text
            """
        ),
        {
            "workspace_id": workspace_id,
            "kind": kind,
            "agent_kind": agent_kind,
            "agent_ref": agent_ref,
            "agent_version": agent_version,
            "inputs": json.dumps(inputs or {}),
            "audit_log_id": audit_log_id,
        },
    )
    return result.scalar_one()


async def end_activity(
    session: AsyncSession,
    activity_id: str,
    *,
    outputs: dict[str, Any] | None = None,
    audit_log_id: int | None = None,
) -> None:
    """Mark an activity finished and stash its outputs.

    Safe to call repeatedly; the latest call wins.
    """
    await session.execute(
        text(
            """
            UPDATE prov_activity
            SET ended_at = clock_timestamp(),
                outputs = CAST(:outputs AS jsonb),
                audit_log_id = COALESCE(:audit_log_id, audit_log_id)
            WHERE id = :id
            """
        ),
        {
            "id": activity_id,
            "outputs": json.dumps(outputs or {}),
            "audit_log_id": audit_log_id,
        },
    )


async def get_activity(session: AsyncSession, activity_id: str) -> Activity | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, kind, agent_kind,
                       agent_ref, agent_version, inputs, outputs,
                       started_at::text, ended_at::text, audit_log_id
                FROM prov_activity WHERE id = :id
                """
            ),
            {"id": activity_id},
        )
    ).mappings().first()
    if not row:
        return None
    return Activity(
        id=row["id"],
        workspace_id=row["workspace_id"],
        kind=row["kind"],
        agent_kind=row["agent_kind"],
        agent_ref=row["agent_ref"],
        agent_version=row["agent_version"],
        inputs=row["inputs"] or {},
        outputs=row["outputs"] or {},
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        audit_log_id=row["audit_log_id"],
    )


async def link_derivation(
    session: AsyncSession,
    *,
    workspace_id: str,
    derived_activity_id: str,
    upstream_activity_id: str,
    kind: str = "derived",
) -> None:
    """Record that ``derived_activity_id`` reused / revised / quoted
    ``upstream_activity_id``.

    Idempotent: the unique constraint on (derived, upstream) makes
    repeat calls no-ops.
    """
    if derived_activity_id == upstream_activity_id:
        raise ValueError("an activity cannot derive from itself")
    if kind not in {"derived", "revised", "quoted"}:
        raise ValueError(f"invalid derivation_kind: {kind}")
    await session.execute(
        text(
            """
            INSERT INTO prov_activity_derivation
              (workspace_id, derived_activity_id, upstream_activity_id,
               derivation_kind)
            VALUES (:ws, :d, :u, :k)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "ws": workspace_id,
            "d": derived_activity_id,
            "u": upstream_activity_id,
            "k": kind,
        },
    )


async def derivation_chain(
    session: AsyncSession,
    activity_id: str,
    *,
    max_depth: int = 10,
) -> list[Activity]:
    """Return the upstream chain reachable from ``activity_id``.

    Order: closest-upstream-first. The recursion is depth-bounded as
    a belt-and-braces; the CHECK constraint already forbids self-loops.
    """
    rows = (
        await session.execute(
            text(
                """
                WITH RECURSIVE walk AS (
                  SELECT pad.upstream_activity_id AS id, 1 AS depth
                  FROM prov_activity_derivation pad
                  WHERE pad.derived_activity_id = :start
                  UNION
                  SELECT pad.upstream_activity_id, w.depth + 1
                  FROM prov_activity_derivation pad
                  JOIN walk w ON w.id = pad.derived_activity_id
                  WHERE w.depth < :max_depth
                )
                SELECT pa.id::text, pa.workspace_id::text, pa.kind,
                       pa.agent_kind, pa.agent_ref, pa.agent_version,
                       pa.inputs, pa.outputs,
                       pa.started_at::text, pa.ended_at::text,
                       pa.audit_log_id
                FROM walk w
                JOIN prov_activity pa ON pa.id = w.id
                ORDER BY w.depth
                """
            ),
            {"start": activity_id, "max_depth": max_depth},
        )
    ).mappings().all()
    return [
        Activity(
            id=row["id"],
            workspace_id=row["workspace_id"],
            kind=row["kind"],
            agent_kind=row["agent_kind"],
            agent_ref=row["agent_ref"],
            agent_version=row["agent_version"],
            inputs=row["inputs"] or {},
            outputs=row["outputs"] or {},
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            audit_log_id=row["audit_log_id"],
        )
        for row in rows
    ]


async def get_edge_provenance(
    session: AsyncSession, edge_id: str
) -> dict[str, Any] | None:
    """Return PROV-O JSON-LD describing an edge's provenance.

    Includes the activity that generated it, the agent associated with
    the activity, and (if present) the source episode it was derived from.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT
                  e.id::text AS edge_id,
                  e.fact,
                  e.created_at::text AS edge_created_at,
                  e.confidence,
                  e.created_by::text AS edge_created_by,
                  e.source_id::text,
                  e.source_kind,
                  a.id::text AS activity_id,
                  a.kind AS activity_kind,
                  a.agent_kind,
                  a.agent_ref,
                  a.agent_version,
                  a.started_at::text AS activity_started_at,
                  a.ended_at::text AS activity_ended_at,
                  ep.id::text AS episode_id,
                  LEFT(COALESCE(ep.content_text, ''), 200) AS episode_snippet,
                  ep.source_kind AS episode_source_kind
                FROM edge e
                LEFT JOIN prov_activity a ON a.id = e.prov_activity_id
                LEFT JOIN episode ep ON ep.id = e.source_id
                  AND e.source_kind = 'episode'
                WHERE e.id = :id
                """
            ),
            {"id": edge_id},
        )
    ).mappings().first()

    if not row:
        return None

    doc: dict[str, Any] = dict(PROV_CONTEXT)
    doc["@id"] = f"dce:edge/{row['edge_id']}"
    doc["@type"] = ["Entity", "dce:Fact"]
    doc["dce:fact"] = row["fact"]
    doc["dce:confidence"] = row["confidence"]
    if row["activity_id"]:
        agent_node: dict[str, Any] = {
            "@id": f"dce:agent/{row['agent_kind']}/{row['agent_ref'] or 'unknown'}",
            "@type": "Agent",
            "dce:agentKind": row["agent_kind"],
        }
        if row["agent_ref"]:
            agent_node["dce:agentRef"] = row["agent_ref"]
        if row["agent_version"]:
            agent_node["dce:agentVersion"] = row["agent_version"]
        activity_node: dict[str, Any] = {
            "@id": f"dce:activity/{row['activity_id']}",
            "@type": "Activity",
            "dce:kind": row["activity_kind"],
            "startedAtTime": row["activity_started_at"],
            "wasAssociatedWith": agent_node,
        }
        if row["activity_ended_at"]:
            activity_node["endedAtTime"] = row["activity_ended_at"]
        doc["wasGeneratedBy"] = activity_node
        doc["wasAttributedTo"] = agent_node
    derived_nodes: list[dict[str, Any]] = []
    if row["episode_id"]:
        derived_nodes.append(
            {
                "@id": f"dce:episode/{row['episode_id']}",
                "@type": ["Entity", "dce:Episode"],
                "dce:snippet": row["episode_snippet"],
                "dce:sourceKind": row["episode_source_kind"],
            }
        )

    # Agent-to-agent derivations (Phase O3): if this edge's activity
    # was informed by other activities, surface them as additional
    # ``wasDerivedFrom`` nodes so the chain is one query away for the
    # agent caller.
    if row["activity_id"]:
        upstream = await derivation_chain(session, row["activity_id"])
        for act in upstream:
            derived_nodes.append(
                {
                    "@id": f"dce:activity/{act.id}",
                    "@type": "Activity",
                    "dce:kind": act.kind,
                    "wasAssociatedWith": {
                        "@id": (
                            f"dce:agent/{act.agent_kind}/"
                            f"{act.agent_ref or 'unknown'}"
                        ),
                        "@type": "Agent",
                        "dce:agentKind": act.agent_kind,
                        **({"dce:agentRef": act.agent_ref}
                           if act.agent_ref else {}),
                    },
                }
            )

    if len(derived_nodes) == 1:
        doc["wasDerivedFrom"] = derived_nodes[0]
    elif derived_nodes:
        doc["wasDerivedFrom"] = derived_nodes
    return doc


async def get_episode_provenance(
    session: AsyncSession, episode_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT
                  ep.id::text AS episode_id,
                  LEFT(COALESCE(ep.content_text, ''), 200) AS snippet,
                  ep.source_kind,
                  ep.ingested_at::text AS ingested_at,
                  a.id::text AS activity_id,
                  a.kind AS activity_kind,
                  a.agent_kind, a.agent_ref, a.agent_version,
                  a.started_at::text AS activity_started_at,
                  a.ended_at::text AS activity_ended_at
                FROM episode ep
                LEFT JOIN prov_activity a ON a.id = ep.prov_activity_id
                WHERE ep.id = :id
                """
            ),
            {"id": episode_id},
        )
    ).mappings().first()

    if not row:
        return None

    doc: dict[str, Any] = dict(PROV_CONTEXT)
    doc["@id"] = f"dce:episode/{row['episode_id']}"
    doc["@type"] = ["Entity", "dce:Episode"]
    doc["dce:snippet"] = row["snippet"]
    doc["dce:sourceKind"] = row["source_kind"]
    if row["activity_id"]:
        agent_node: dict[str, Any] = {
            "@id": f"dce:agent/{row['agent_kind']}/{row['agent_ref'] or 'unknown'}",
            "@type": "Agent",
            "dce:agentKind": row["agent_kind"],
            "dce:agentRef": row["agent_ref"],
        }
        if row["agent_version"]:
            agent_node["dce:agentVersion"] = row["agent_version"]
        activity_node: dict[str, Any] = {
            "@id": f"dce:activity/{row['activity_id']}",
            "@type": "Activity",
            "dce:kind": row["activity_kind"],
            "startedAtTime": row["activity_started_at"],
            "wasAssociatedWith": agent_node,
        }
        if row["activity_ended_at"]:
            activity_node["endedAtTime"] = row["activity_ended_at"]
        doc["wasGeneratedBy"] = activity_node
    return doc
