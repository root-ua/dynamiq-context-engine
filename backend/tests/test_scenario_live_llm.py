"""End-to-end live test against the real Anthropic API.

Opt-in: marked ``@pytest.mark.live_llm`` so ``pytest`` (the default
target) skips it. Run with ``pytest -m live_llm`` after exporting
``ANTHROPIC_API_KEY`` (the user provided one for this; rotate after
the test pass).

The test asks Claude to use our MCP tools to land three facts about
Anthropic, then queries one of the facts back. Costs ~$0.05 per run
on ``claude-haiku-4-5``.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest
from sqlalchemy import text

from app.api.mcp.tools import TOOLS, invoke_tool
from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import entity as entity_mod

pytestmark = pytest.mark.live_llm


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user_id=user_id, email="agent@x.com",
        workspace_id=workspace_id, role="editor",
        claims={"kind": "agent_token"}, kind="service",
    )


def _tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema.model_json_schema(),
        }
        for spec in TOOLS
    ]


@pytest.mark.asyncio
async def test_claude_builds_graph_via_mcp(enterprise_workspace):
    """Real Anthropic API call — costs ~$0.05.

    We don't assert on a specific tool sequence (Claude picks its
    own); we assert on the outcome: an entity for Anthropic exists
    and at least one fact about it landed.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    # Pre-seed an Anthropic entity so the agent doesn't need to invent
    # entity types in `strict` mode. (The ontology comes with `organization`
    # by default; we create the entity for it.)
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        anthropic_org = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Anthropic", embed=False,
        )

    prompt = (
        "Use the MCP tools to record three short facts about the company "
        "'Anthropic' (entity id: " + anthropic_org.id + "). Use `add_fact` "
        "with appropriate relation slugs from `ontology_describe` if you "
        "need to discover them. Keep facts concise."
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt}
    ]
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        for _ in range(8):
            response = await client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=2048,
                tools=_tool_defs(),
                messages=messages,
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [
                b.text for b in response.content if b.type == "text"
            ]
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": []}
            for t in text_blocks:
                assistant_msg["content"].append({"type": "text", "text": t})
            for tu in tool_uses:
                assistant_msg["content"].append(
                    {
                        "type": "tool_use",
                        "id": tu.id,
                        "name": tu.name,
                        "input": tu.input,
                    }
                )
            messages.append(assistant_msg)

            if not tool_uses:
                break

            tool_results = []
            for tu in tool_uses:
                result = await invoke_tool(
                    s,
                    workspace_id=ws_id,
                    actor_id=e.alice.id,
                    name=tu.name,
                    arguments=tu.input or {},
                    principal=principal,
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(result),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        # Verify the side effect: at least one edge with Anthropic as
        # subject landed.
        rows = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE subject_id = CAST(:id AS uuid) "
                    "  AND workspace_id = CAST(:w AS uuid)"
                ),
                {"id": anthropic_org.id, "w": ws_id},
            )
        ).scalar_one()

    assert rows >= 1, "agent failed to land any facts about Anthropic"
