"""MCP server endpoints.

Exposes two faces of the same tool registry:

1. **REST** (for Web UI, curl, non-MCP agents):
   - ``GET /mcp/tools`` — tool catalog with JSON Schemas.
   - ``POST /mcp/invoke`` — invoke ``{name, arguments}``.

2. **MCP over SSE** (for Claude Desktop, Cursor, OpenAI Agents, etc.):
   - ``GET /mcp/sse`` — server-sent events stream.
   - ``POST /mcp/messages`` — JSON-RPC messages.

Both surfaces share the same workspace resolution (JWT → workspace_id
via RLS) and produce an ``agent_tool_call`` audit row per invocation.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.mcp.tools import TOOLS, TOOLS_BY_NAME, invoke_tool
from app.auth.deps import CurrentPrincipal, DbSession
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ---------------------------------------------------------------------------
# REST surface
# ---------------------------------------------------------------------------

@router.get("/tools")
async def list_tools(_: CurrentPrincipal) -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema.model_json_schema(),
            }
            for t in TOOLS
        ]
    }


@router.post("/invoke")
async def invoke(
    request: Request, principal: CurrentPrincipal, session: DbSession,
) -> dict[str, Any]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    body = await request.json()
    name = body.get("name")
    args = body.get("arguments", {}) or {}
    session_id = body.get("session_id")
    if not isinstance(name, str) or name not in TOOLS_BY_NAME:
        raise HTTPException(404, f"unknown tool: {name}")

    # Open (or reuse) an agent session row so calls aggregate nicely.
    if not session_id:
        session_id = await _ensure_agent_session(session, principal, client=body.get("client", "web"))

    result = await invoke_tool(
        session,
        workspace_id=principal.workspace_id,
        actor_id=principal.user_id,
        name=name,
        arguments=args,
        session_id=session_id,
        principal=principal,
    )
    return {"session_id": session_id, "result": result}


@router.post("/sessions")
async def create_session(
    principal: CurrentPrincipal, session: DbSession,
    client: str = "web",
) -> dict[str, str]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    sid = await _ensure_agent_session(session, principal, client=client)
    return {"session_id": sid}


async def _ensure_agent_session(
    session, principal, *, client: str,
) -> str:
    sid = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO agent_session (id, workspace_id, user_id, client)
            VALUES (:id, :workspace_id, :user_id, :client)
            """
        ),
        {
            "id": sid, "workspace_id": principal.workspace_id,
            "user_id": principal.user_id, "client": client,
        },
    )
    return sid


# ---------------------------------------------------------------------------
# MCP JSON-RPC (SSE + messages)
# ---------------------------------------------------------------------------
#
# A simplified JSON-RPC 2.0 implementation sufficient for Claude Desktop /
# mcp-client libraries. It supports:
#   - initialize
#   - tools/list
#   - tools/call
#
# SSE channel streams notifications. The current implementation keeps the
# connection alive with a heartbeat; real-time tool progress events are a
# follow-up.

@router.get("/rpc")
async def rpc_probe() -> dict[str, str]:
    """Some MCP clients issue a GET before the first JSON-RPC POST to
    check liveness. Return a 200 + a friendly JSON body so they don't
    405 and abort the connection."""
    return {
        "protocol": "mcp",
        "transport": "streamable-http",
        "version": "2025-06-18",
        "hint": "POST JSON-RPC 2.0 messages here with Authorization: Bearer <token>",
    }


@router.post("/rpc")
async def rpc_call(
    request: Request, principal: CurrentPrincipal, session: DbSession,
) -> JSONResponse:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    body = await request.json()

    method = body.get("method")
    params = body.get("params", {}) or {}
    req_id = body.get("id")

    if method == "initialize":
        return _rpc_ok(req_id, {
            "protocolVersion": "2025-06-18",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {
                "name": "dynamiq-context-engine",
                "version": "0.1.0",
            },
        })

    if method == "tools/list":
        return _rpc_ok(req_id, {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema.model_json_schema(),
                }
                for t in TOOLS
            ]
        })

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        if tool_name not in TOOLS_BY_NAME:
            return _rpc_err(req_id, -32601, f"unknown tool: {tool_name}")

        session_id = await _ensure_agent_session(session, principal, client=params.get("client", "mcp"))
        result = await invoke_tool(
            session,
            workspace_id=principal.workspace_id,
            actor_id=principal.user_id,
            name=tool_name,
            arguments=arguments,
            session_id=session_id,
            principal=principal,
        )
        return _rpc_ok(req_id, {
            "content": [{"type": "text", "text": _to_text(result)}],
            "isError": "error" in result,
            "_meta": {"session_id": session_id},
        })

    return _rpc_err(req_id, -32601, f"unknown method: {method}")


def _rpc_ok(req_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _rpc_err(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _to_text(value: Any) -> str:
    import json
    return json.dumps(value, indent=2, default=str)
