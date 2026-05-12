from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.auth.deps import CurrentPrincipal, DbSession

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def list_audit(
    principal: CurrentPrincipal, session: DbSession,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
):
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    result = await session.execute(
        text(
            """
            SELECT id, actor_kind, actor_id::text, action, target_kind,
                   target_id::text, diff, created_at::text
            FROM audit_log
            WHERE workspace_id = :workspace_id
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"workspace_id": principal.workspace_id, "limit": limit, "offset": offset},
    )
    return [dict(r) for r in result.mappings()]


@router.get("/agent-sessions")
async def list_agent_sessions(
    principal: CurrentPrincipal, session: DbSession,
    limit: int = Query(default=50, le=200),
):
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    result = await session.execute(
        text(
            """
            SELECT s.id::text, s.client, s.started_at::text, s.ended_at::text,
                   COUNT(c.id) AS tool_calls
            FROM agent_session s
            LEFT JOIN agent_tool_call c ON c.session_id = s.id
            WHERE s.workspace_id = :workspace_id
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT :limit
            """
        ),
        {"workspace_id": principal.workspace_id, "limit": limit},
    )
    return [dict(r) for r in result.mappings()]


@router.get("/agent-sessions/{session_id}/calls")
async def list_agent_calls(
    session_id: str, _: CurrentPrincipal, session: DbSession,
    limit: int = Query(default=200, le=500),
):
    result = await session.execute(
        text(
            """
            SELECT id::text, tool, input, output, error, latency_ms,
                   created_at::text
            FROM agent_tool_call
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"session_id": session_id, "limit": limit},
    )
    return [dict(r) for r in result.mappings()]
