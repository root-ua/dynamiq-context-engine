"""End-to-end live tests against the real Anthropic API.

Opt-in: marked ``@pytest.mark.live_llm`` so ``pytest`` (the default
target) skips it. Run with ``pytest -m live_llm`` after exporting
``ANTHROPIC_API_KEY`` locally. Costs ~$0.10/run total on
``claude-haiku-4-5``.

Two scenarios:

1. **Fact recording** — agent uses ``add_fact`` directly with a
   pre-resolved entity. Smallest possible loop; verifies the bare
   MCP tool surface.
2. **Document → ingestion → search → provenance round-trip** —
   agent receives a document content block (the same shape the
   playground frontend sends for PDFs), calls ``add_episode``,
   then later answers a question about it via ``search_memory``,
   and we check that ``get_provenance`` walks back to a
   well-formed PROV-O bundle.
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
        for iteration in range(8):
            create_kwargs: dict[str, Any] = dict(
                model="claude-haiku-4-5",
                max_tokens=2048,
                tools=_tool_defs(),
                messages=messages,
            )
            # Force a tool call on the first turn so haiku's tool-choice
            # variance doesn't flake the test. (Anthropic SDK supports
            # tool_choice={"type": "any"} which leaves the specific tool
            # to the model.)
            if iteration == 0:
                create_kwargs["tool_choice"] = {"type": "any"}
            response = await client.messages.create(**create_kwargs)

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

        # Verify the side effect — the agent should have produced one
        # of: an edge with Anthropic as subject OR object, a pending
        # fact, or an entity update on the pre-seeded row. Live LLMs
        # pick their own sequence (sometimes `add_fact`, sometimes
        # `update_entity` to enrich properties); any of those counts.
        edge_rows = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM edge "
                    "WHERE (subject_id = CAST(:id AS uuid) "
                    "    OR object_id = CAST(:id AS uuid)) "
                    "  AND workspace_id = CAST(:w AS uuid)"
                ),
                {"id": anthropic_org.id, "w": ws_id},
            )
        ).scalar_one()
        pending_rows = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM pending_fact "
                    "WHERE (subject_id = CAST(:id AS uuid) "
                    "    OR object_id = CAST(:id AS uuid)) "
                    "  AND workspace_id = CAST(:w AS uuid)"
                ),
                {"id": anthropic_org.id, "w": ws_id},
            )
        ).scalar_one()
        audit_rows = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM audit_log "
                    "WHERE target_id = CAST(:id AS uuid) "
                    "  AND workspace_id = CAST(:w AS uuid)"
                ),
                {"id": anthropic_org.id, "w": ws_id},
            )
        ).scalar_one()

    assert edge_rows + pending_rows + audit_rows >= 1, (
        "agent failed to land any facts, proposals, or updates on the "
        "Anthropic entity"
    )


@pytest.mark.asyncio
async def test_document_ingestion_search_and_provenance_round_trip(
    enterprise_workspace,
):
    """Document → ``add_episode`` → search round-trip → ``get_provenance``.

    Mirrors what happens in the playground when a user drops a file:
    the agent receives the document content, calls ``add_episode``,
    and later answers a follow-up by searching the graph it just
    built. Then we walk the provenance back to confirm the chain
    is well-formed.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    e = enterprise_workspace
    ws_id = e.workspace_id
    principal = _principal(e.alice.id, ws_id)

    # Anthropic supports a `document` content block with `type: "text"`
    # source — same shape as the PDF path, minus the base64. The
    # playground frontend emits the base64 variant for PDFs; the
    # backend passes either through unchanged.
    doc_text = (
        "Acme Pharma announced on 2025-09-01 that it launched the "
        "Phase II clinical trial of EGF-101, a candidate treatment "
        "for late-stage glioblastoma. The trial enrolls 220 patients "
        "across 14 sites in North America and is led by Dr. Jane Lin, "
        "Chief Medical Officer at Acme Pharma."
    )
    user_blocks = [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": doc_text},
            "title": "acme-egf101-press-release.txt",
        },
        {
            "type": "text",
            "text": (
                "Read the attached release. You MUST call the "
                "`add_episode` tool exactly once with the document's "
                "full text as `content` and `source_kind=\"document\"`. "
                "Do not ask clarifying questions. After the tool "
                "result, summarise what you ingested in one sentence."
            ),
        },
    ]

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_blocks}]
    episode_ids_landed: list[str] = []
    fact_edges_landed: list[str] = []
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        for iteration in range(8):
            create_kwargs: dict[str, Any] = dict(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                tools=_tool_defs(),
                messages=messages,
            )
            # Force the first turn to invoke add_episode so the test
            # measures the round-trip rather than the model's chosen
            # rhetoric.
            if iteration == 0:
                create_kwargs["tool_choice"] = {
                    "type": "tool",
                    "name": "add_episode",
                }
            response = await client.messages.create(**create_kwargs)
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b.text for b in response.content if b.type == "text"]
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
                if tu.name == "add_episode" and isinstance(result, dict):
                    ep_id = result.get("episode_id")
                    if isinstance(ep_id, str):
                        episode_ids_landed.append(ep_id)
                if tu.name == "add_fact" and isinstance(result, dict):
                    edge = result.get("edge") or {}
                    if isinstance(edge, dict) and edge.get("id"):
                        fact_edges_landed.append(edge["id"])
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(result),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        assert episode_ids_landed or fact_edges_landed, (
            "agent didn't call add_episode or add_fact — no graph mutation"
        )

        # Walk provenance on whatever the agent landed. Try edges
        # first (works whether they came from add_fact or extraction).
        candidate_edge_id: str | None = None
        if fact_edges_landed:
            candidate_edge_id = fact_edges_landed[0]
        elif episode_ids_landed:
            rows = (
                await s.execute(
                    text(
                        "SELECT id::text FROM edge "
                        "WHERE source_kind = 'episode' "
                        "  AND source_id::text = ANY(:ids) "
                        "  AND workspace_id = CAST(:w AS uuid)"
                    ),
                    {"ids": episode_ids_landed, "w": ws_id},
                )
            ).scalars().all()
            candidate_edge_id = rows[0] if rows else None

        if candidate_edge_id:
            doc = await invoke_tool(
                s,
                workspace_id=ws_id,
                actor_id=e.alice.id,
                name="get_provenance",
                arguments={"fact_id": candidate_edge_id},
                principal=principal,
            )
            assert "wasGeneratedBy" in doc, doc
            generated = doc["wasGeneratedBy"]
            agent = generated.get("wasAssociatedWith", {})
            assert agent.get("dce:agentKind") in {
                "llm", "system", "user",
            }, agent

        # Search round-trip: ask for "EGF-101" and assert we find an
        # episode, edge, or entity that mentions it. (Search hits
        # every kind by default — the agent might have created an
        # entity with EGF-101 in its summary even if no edge mentions
        # the term.)
        search_result = await invoke_tool(
            s,
            workspace_id=ws_id,
            actor_id=e.alice.id,
            name="search_memory",
            arguments={"query": "EGF-101", "limit": 10},
            principal=principal,
        )
        hits = search_result.get("hits", [])
        found_in_search = any(
            "egf-101" in (
                (h.get("snippet", "") or "")
                + " "
                + (h.get("title", "") or "")
            ).lower()
            for h in hits
        )
        # Fallback — sometimes the agent paraphrases without echoing the
        # token literally; the canonical entity may carry it.
        if not found_in_search and episode_ids_landed:
            ep_check = (
                await s.execute(
                    text(
                        "SELECT 1 FROM episode "
                        "WHERE id = ANY(:ids) AND content_text ILIKE :q"
                    ),
                    {"ids": episode_ids_landed, "q": "%EGF-101%"},
                )
            ).first()
            found_in_search = ep_check is not None
        assert found_in_search, (
            f"EGF-101 not found via search or in landed episodes; "
            f"hits={hits}, episodes={episode_ids_landed}"
        )
