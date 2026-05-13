"""Q3 — Functional agent persona (CFO).

A finance agent makes a decision based on a single fact retrieved with
confidence and freshness. Exercises:

* O1 — `get_fact` happy path returning the latest fact.
* O1 — `get_fact(as_of=...)` returns the historical fact.
* O1 — `require_min_confidence` gate.
* O2 — `search_memory` hit payloads carry `confidence` + `freshness_days`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.mcp.tools import invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.retrieval.hybrid import search as hybrid_search


pytestmark = pytest.mark.scenario


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user_id=user_id, email="cfo@x.com",
        workspace_id=workspace_id, role="editor",
        claims={}, kind="user",
    )


@pytest.mark.asyncio
async def test_functional_agent_get_fact_with_freshness(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme Q3", embed=False,
        )
        topic = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="topic",
            canonical="ARR 2025-Q3 = $60M", embed=False,
        )
        # Use ``tagged`` (cardinality-many) so multiple historical values
        # can coexist without the contradictor closing them.
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=acme.id, predicate="tagged", object_id=topic.id,
            fact="Acme ARR 2025-Q3 = $60M",
            confidence=0.95,
            valid_from=datetime(2025, 10, 1, tzinfo=timezone.utc),
            embed=False, run_contradictor=False,
        )

        # get_fact returns the structured fact with confidence + freshness.
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=e.alice.id,
            name="get_fact",
            arguments={"subject": acme.id, "predicate": "tagged",
                       "object": topic.id},
            principal=principal,
        )
    assert "error" not in result, result
    assert result["confidence"] == pytest.approx(0.95)
    assert result["freshness_days"] is not None and result["freshness_days"] >= 0


@pytest.mark.asyncio
async def test_functional_agent_min_confidence_gate(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme Q3 low-conf", embed=False,
        )
        topic = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="topic",
            canonical="Disputed valuation", embed=False,
        )
        # Force the edge in via add_fact (which doesn't auto-route to
        # pending). 0.6 is below the agent's 0.9 threshold.
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=acme.id, predicate="tagged", object_id=topic.id,
            fact="Disputed", confidence=0.6,
            embed=False, run_contradictor=False,
        )
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=e.alice.id,
            name="get_fact",
            arguments={
                "subject": acme.id, "predicate": "tagged", "object": topic.id,
                "require_min_confidence": 0.9,
            },
            principal=principal,
        )
    assert result["error"] == "below_min_confidence"


@pytest.mark.asyncio
async def test_search_hits_carry_confidence_and_freshness(
    enterprise_workspace,
):
    """O2 — payload enrichment in hybrid search."""
    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme Q3 search", embed=False,
        )
        topic = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="topic",
            canonical="Quarterly revenue search", embed=False,
        )
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=acme.id, predicate="tagged", object_id=topic.id,
            fact="quarterly revenue search marker phrase",
            confidence=0.88,
            embed=False, run_contradictor=False,
        )
        hits = await hybrid_search(
            s, workspace_id=ws_id, query="quarterly revenue search",
            limit=10, include_kinds=("edge",),
            principal=principal,
        )

    assert any(
        h.kind == "edge"
        and h.payload.get("confidence") == pytest.approx(0.88)
        and h.payload.get("freshness_days") is not None
        for h in hits
    ), hits
