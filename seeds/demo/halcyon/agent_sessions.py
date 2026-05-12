"""Agent sessions with plausible MCP tool-call history.

Shows the Agent Console isn't a stub: click into the session, see real
calls with realistic arguments + outputs. The tool names match the
actual MCP tool registry (see `backend/app/api/mcp/tools.py`).
"""

from datetime import UTC, datetime

from seeds.demo.halcyon._types import AgentSessionSeed, AgentToolCallSeed


def _dt(y: int, m: int, d: int, h: int, mn: int) -> datetime:
    return datetime(y, m, d, h, mn, tzinfo=UTC)


AGENT_SESSIONS: tuple[AgentSessionSeed, ...] = (
    AgentSessionSeed(
        key="session.zephyr_prep",
        client="claude-code",
        started_at=_dt(2025, 12, 2, 17, 30),
        calls=(
            AgentToolCallSeed(
                tool="search_memory",
                arguments={
                    "query": "Zephyr pilot eval accuracy issue",
                    "limit": 10,
                },
                result={
                    "hits": [
                        {
                            "kind": "document",
                            "title": "Zephyr pilot postmortem",
                            "score": 0.94,
                            "snippet": (
                                "On Oct 2, Jordan Reyes filed a ticket "
                                "showing Orbit's agent-eval score disagreed "
                                "with his human-labelled golden set on "
                                "17% of samples."
                            ),
                        },
                        {
                            "kind": "edge",
                            "title": "Zephyr Data signed 1-year Orbit contract",
                            "score": 0.78,
                        },
                        {
                            "kind": "episode",
                            "title": "Founders sync, Oct 6",
                            "score": 0.71,
                        },
                    ],
                    "total": 3,
                },
                latency_ms=142,
                occurred_at=_dt(2025, 12, 2, 17, 30),
            ),
            AgentToolCallSeed(
                tool="get_entity_history",
                arguments={"entity": "Zephyr Data", "predicate": "customer_of"},
                result={
                    "edges": [
                        {
                            "fact": (
                                "Zephyr Data signed a Letter of Intent to "
                                "pilot Orbit."
                            ),
                            "valid_time": "[2025-09-23, 2025-10-14)",
                            "invalidated_reason": (
                                "LOI withdrawn after eval-accuracy issue "
                                "surfaced during pilot."
                            ),
                        },
                        {
                            "fact": (
                                "Zephyr Data signed 1-year Orbit contract "
                                "($84K ACV)."
                            ),
                            "valid_time": "[2025-11-19, 2026-11-19)",
                        },
                    ]
                },
                latency_ms=89,
                occurred_at=_dt(2025, 12, 2, 17, 31),
            ),
            AgentToolCallSeed(
                tool="get_entity",
                arguments={"entity": "Jordan Reyes"},
                result={
                    "id": "<placeholder>",
                    "canonical": "Jordan Reyes",
                    "type": "person",
                    "props": {
                        "role": "Staff Engineer",
                        "email": "jordan@zephyrdata.io",
                    },
                    "aliases": ["Jordan", "@jreyes", "J. Reyes"],
                    "summary": (
                        "Staff engineer at Zephyr Data. Owned the Orbit "
                        "pilot on their side."
                    ),
                },
                latency_ms=67,
                occurred_at=_dt(2025, 12, 2, 17, 31),
            ),
            AgentToolCallSeed(
                tool="add_fact",
                arguments={
                    "subject": "Jordan Reyes",
                    "predicate": "agreed_to",
                    "object": "reference_calls",
                    "fact": (
                        "Jordan agreed to take 2–3 reference calls for "
                        "prospects in Q1 2026."
                    ),
                    "confidence": 0.9,
                    "source_kind": "agent",
                },
                result={"edge_id": "<placeholder>", "status": "created"},
                latency_ms=204,
                occurred_at=_dt(2025, 12, 2, 17, 32),
            ),
        ),
    ),
    AgentSessionSeed(
        key="session.prism_scoping",
        client="cursor",
        started_at=_dt(2026, 1, 14, 21, 12),
        calls=(
            AgentToolCallSeed(
                tool="search_memory",
                arguments={
                    "query": "orbit ingestion throughput p99 latency",
                    "limit": 6,
                },
                result={
                    "hits": [
                        {
                            "kind": "document",
                            "title": "2026 strategy memo",
                            "score": 0.88,
                            "snippet": (
                                "We're at 1.8s on the ingestion path; we "
                                "need sub-300ms."
                            ),
                        },
                        {
                            "kind": "document",
                            "title": "Orbit 1.1 — launch notes",
                            "score": 0.71,
                        },
                    ],
                    "total": 2,
                },
                latency_ms=118,
                occurred_at=_dt(2026, 1, 14, 21, 12),
            ),
            AgentToolCallSeed(
                tool="list_entities",
                arguments={
                    "type": "project",
                    "query": "prism",
                },
                result={
                    "entities": [
                        {
                            "canonical": "Project Prism",
                            "type": "project",
                            "summary": (
                                "Internal codename for the Q1 2026 "
                                "multi-tenant re-architecture of Orbit's "
                                "storage layer."
                            ),
                        }
                    ]
                },
                latency_ms=54,
                occurred_at=_dt(2026, 1, 14, 21, 13),
            ),
            AgentToolCallSeed(
                tool="get_entity",
                arguments={"entity": "Project Prism"},
                result={
                    "canonical": "Project Prism",
                    "type": "project",
                    "props": {
                        "status": "in_progress",
                        "target_ship": "2026-04-30",
                        "lead_person_key": "person.alex_park",
                    },
                    "summary": (
                        "Q1 2026 multi-tenant re-architecture. 10x "
                        "ingestion throughput, P99 < 300ms per tenant."
                    ),
                },
                latency_ms=71,
                occurred_at=_dt(2026, 1, 14, 21, 13),
            ),
        ),
    ),
)
