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
AgentKind = str  # 'llm'|'user'|'system'|'connector'


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
                  ep.external_url AS episode_url,
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
    if row["episode_id"]:
        doc["wasDerivedFrom"] = {
            "@id": f"dce:episode/{row['episode_id']}",
            "@type": ["Entity", "dce:Episode"],
            "dce:snippet": row["episode_snippet"],
            "dce:sourceKind": row["episode_source_kind"],
            "dce:externalUrl": row["episode_url"],
        }
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
                  ep.external_url,
                  ep.source_kind,
                  ep.ingested_at::text AS ingested_at,
                  a.id::text AS activity_id,
                  a.kind AS activity_kind,
                  a.agent_kind, a.agent_ref, a.agent_version,
                  a.started_at::text AS activity_started_at,
                  a.ended_at::text AS activity_ended_at,
                  ep.connector_instance_id::text AS connector_id,
                  ci.connector_kind
                FROM episode ep
                LEFT JOIN prov_activity a ON a.id = ep.prov_activity_id
                LEFT JOIN connector_instance ci ON ci.id = ep.connector_instance_id
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
    doc["dce:externalUrl"] = row["external_url"]
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
    if row["connector_id"]:
        doc["dce:fromConnector"] = {
            "@id": f"dce:connector/{row['connector_id']}",
            "@type": "Agent",
            "dce:connectorKind": row["connector_kind"],
        }
    return doc
