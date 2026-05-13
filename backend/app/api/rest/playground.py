"""Chat-style playground SSE route.

The playground page in the web app lets a workspace member chat with
a real Claude agent that has the platform's 22 MCP tools registered.
The agent issues tool calls; the platform invokes them against the
caller's workspace; tool results flow back to the agent; the chat
streams.

File ingestion model: the platform does NOT parse PDFs / images
itself. The frontend converts a dropped file to a base64 Anthropic
``document`` / ``image`` content block and hands it to Claude as
part of the user message. Claude reads the file natively, decides
which facts to record, and calls ``add_episode`` / ``add_fact`` over
MCP. That's the architectural guardrail: ingestion is the agent's
job, the platform owns the graph.

Wire format: Server-Sent Events. Each event is a single JSON line
with one of these shapes:

```
{"type":"text_delta","text":"..."}
{"type":"tool_call","id":"toolu_…","name":"search_memory","input":{...}}
{"type":"tool_result","tool_use_id":"toolu_…","content":"<json>"}
{"type":"done"}
{"type":"error","detail":"..."}
```

The frontend renders the running assistant text on the left and the
tool-call timeline on the right.

Auth: session JWT (web users) or agent token. Workspace is taken from
the resolved principal.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.mcp.tools import TOOLS, invoke_tool
from app.auth.deps import CurrentPrincipal, DbSession
from app.core.config import get_settings
from app.core.logging import get_logger

try:  # Optional deps — the playground route is only useful when both are present.
    import anthropic
    from sse_starlette.sse import EventSourceResponse
except ImportError:  # pragma: no cover — runtime fallback only.
    anthropic = None  # type: ignore[assignment]
    EventSourceResponse = None  # type: ignore[assignment]

log = get_logger(__name__)

router = APIRouter(prefix="/playground", tags=["playground"])


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    # Either a plain string (text-only turn) or a list of Anthropic
    # content blocks: ``{"type": "text" | "image" | "document", ...}``.
    # The frontend uses the block form when a user drops a file —
    # Claude reads the file natively, no platform-side parsing.
    content: str | list[dict[str, Any]]


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    model: str | None = None
    max_tokens: int = Field(default=2048, ge=64, le=8192)


def _tool_definitions() -> list[dict[str, Any]]:
    """Render the platform's MCP tools as Anthropic-tool-format defs."""
    out: list[dict[str, Any]] = []
    for spec in TOOLS:
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema.model_json_schema(),
            }
        )
    return out


async def _run_loop(
    *,
    session,
    workspace_id: str,
    actor_id: str | None,
    principal,
    model: str,
    max_tokens: int,
    messages: list[dict[str, Any]],
):
    """Generator that yields SSE events as the model + tool loop progresses."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        yield {
            "event": "message",
            "data": json.dumps(
                {"type": "error", "detail": "ANTHROPIC_API_KEY is not configured"}
            ),
        }
        return

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    tools = _tool_definitions()

    conversation: list[dict[str, Any]] = list(messages)

    # Hard cap on agent loop iterations so a runaway model can't burn the
    # whole token quota.
    for _ in range(16):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=conversation,
        )

        text_chunks: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                text_chunks.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        if text_chunks:
            full = "".join(text_chunks)
            yield {
                "event": "message",
                "data": json.dumps({"type": "text_delta", "text": full}),
            }

        if not tool_uses:
            yield {"event": "message", "data": json.dumps({"type": "done"})}
            return

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": []}
        for chunk in text_chunks:
            assistant_msg["content"].append({"type": "text", "text": chunk})
        for tu in tool_uses:
            assistant_msg["content"].append(
                {
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                }
            )
        conversation.append(assistant_msg)

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "tool_call",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    }
                ),
            }
            result = await invoke_tool(
                session,
                workspace_id=workspace_id,
                actor_id=actor_id,
                name=tu["name"],
                arguments=tu["input"] or {},
                principal=principal,
            )
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result,
                    }
                ),
            }
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps(result),
                }
            )
        conversation.append({"role": "user", "content": tool_results})

    yield {
        "event": "message",
        "data": json.dumps(
            {"type": "error", "detail": "agent loop hit iteration cap"}
        ),
    }


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    principal: CurrentPrincipal,
    session: DbSession,
):
    if anthropic is None or EventSourceResponse is None:
        raise HTTPException(
            503,
            "playground requires anthropic + sse-starlette; install backend "
            "extras (uv sync)",
        )
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    if principal.role not in ("editor", "admin", "owner"):
        raise HTTPException(403, "playground requires editor+ role")

    settings = get_settings()
    model = payload.model or settings.playground_model
    messages = [m.model_dump() for m in payload.messages]

    return EventSourceResponse(
        _run_loop(
            session=session,
            workspace_id=principal.workspace_id,
            actor_id=principal.user_id,
            principal=principal,
            model=model,
            max_tokens=payload.max_tokens,
            messages=messages,
        )
    )
