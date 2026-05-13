"""O1 — `get_fact` MCP tool.

Decision-support shortcut. Each test invokes the tool through
``invoke_tool`` so the principal/auth wiring is exercised too.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.api.mcp.tools import invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user_id=user_id, email="t@x.com",
        workspace_id=workspace_id, role="editor",
        claims={}, kind="user",
    )


@pytest.mark.asyncio
async def test_get_fact_returns_structured_response(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as s:
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.92,
            embed=False, run_contradictor=False,
        )
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=user_id,
            name="get_fact",
            arguments={"subject": two_people["alice"], "predicate": "works_at"},
            principal=_principal(user_id, ws_id),
        )
    assert "error" not in result, result
    assert result["fact"] == "Alice works at Acme"
    assert result["confidence"] == pytest.approx(0.92)
    assert result["freshness_days"] is not None
    assert result["wasGeneratedBy"] is None or "@id" in result["wasGeneratedBy"]


@pytest.mark.asyncio
async def test_get_fact_no_live_edge_returns_no_fact(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as s:
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=user_id,
            name="get_fact",
            arguments={"subject": two_people["alice"], "predicate": "works_at"},
            principal=_principal(user_id, ws_id),
        )
    assert result == {"error": "no_fact"}


@pytest.mark.asyncio
async def test_get_fact_below_min_confidence(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as s:
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            confidence=0.6,
            embed=False, run_contradictor=False,
        )
        result = await invoke_tool(
            s, workspace_id=ws_id, actor_id=user_id,
            name="get_fact",
            arguments={
                "subject": two_people["alice"], "predicate": "works_at",
                "require_min_confidence": 0.9,
            },
            principal=_principal(user_id, ws_id),
        )
    assert result["error"] == "below_min_confidence"


@pytest.mark.asyncio
async def test_get_fact_as_of_returns_historical(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as s:
        # Cardinality-one — adding two values closes the prior one.
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=two_people["acme"],
            fact="Alice works at Acme",
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
            embed=False, run_contradictor=False,
        )
        globex = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Globex GF", embed=False,
        )
        await edge_mod.add_fact(
            s, workspace_id=ws_id,
            subject_id=two_people["alice"], predicate="works_at",
            object_id=globex.id,
            fact="Alice works at Globex",
            valid_from=datetime(2025, 6, 1, tzinfo=UTC),
            embed=False, run_contradictor=False,
        )
        # as_of inside 2024 → Acme.
        historical = await invoke_tool(
            s, workspace_id=ws_id, actor_id=user_id,
            name="get_fact",
            arguments={
                "subject": two_people["alice"], "predicate": "works_at",
                "as_of": "2024-06-01T00:00:00Z",
            },
            principal=_principal(user_id, ws_id),
        )
    assert "error" not in historical, historical
    if historical.get("multiple"):
        assert any(c["object"]["id"] == two_people["acme"]
                   for c in historical["candidates"])
    else:
        assert historical["object"]["id"] == two_people["acme"]
