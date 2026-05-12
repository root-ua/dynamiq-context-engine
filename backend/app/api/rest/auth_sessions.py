"""BetterAuth session management endpoints.

BetterAuth's `session` table lives in our Postgres (see migration 0003).
Touching it from here is intentional: we want a single "sign out
everywhere" action that kills every live session for the caller without
bouncing through the BetterAuth HTTP API.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from app.auth.deps import CurrentPrincipal
from app.core.logging import get_logger
from app.db.session import session_scope

router = APIRouter(prefix="/auth", tags=["auth"])

log = get_logger(__name__)


@router.post(
    "/revoke-all-sessions",
    status_code=204,
    response_class=Response,
)
async def revoke_all_sessions(principal: CurrentPrincipal) -> None:
    """Invalidate every BetterAuth session the caller has.

    Useful for "sign out everywhere" and after password reset. Agent
    tokens skip this — they're not BetterAuth sessions.
    """
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(
            status_code=400,
            detail="not applicable to agent tokens",
        )

    async with session_scope(user_id=principal.user_id) as session:
        # BetterAuth's session."userId" is text (not uuid); no cast needed.
        result = await session.execute(
            text('DELETE FROM "session" WHERE "userId" = :uid'),
            {"uid": principal.user_id},
        )
        log.info(
            "auth.sessions.revoked_all",
            user_id=principal.user_id,
            count=result.rowcount,
        )
