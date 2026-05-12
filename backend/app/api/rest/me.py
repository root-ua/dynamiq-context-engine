from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from app.auth.deps import CurrentPrincipal
from app.db.session import session_scope

router = APIRouter(tags=["auth"])


@router.get("/me")
async def me(principal: CurrentPrincipal) -> dict[str, str | None]:
    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "workspace_id": principal.workspace_id,
        "role": principal.role,
    }


@router.delete("/me", status_code=204, response_class=Response)
async def delete_me(principal: CurrentPrincipal) -> None:
    """Delete the caller's account.

    Agent tokens can't call this — account deletion is a high-impact
    action that must go through a real browser session. The UI then
    signs the user out post-delete.

    Cleanup order matters:
      1. NULL out author references on records we keep (content authored
         by this user remains visible to other workspace members, but
         stops pointing at the deleted user).
      2. Let CASCADE drop workspace memberships, agent tokens, BetterAuth
         sessions, etc.
      3. Delete the app_user row + BetterAuth `user` row.
    """
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(
            status_code=403,
            detail="agent tokens cannot delete the user account",
        )

    user_id = principal.user_id
    async with session_scope() as session:
        # NULL out non-cascading FKs. These tables have `REFERENCES
        # app_user(id)` without ON DELETE, so a bare DELETE would fail.
        for table_col in (
            ("entity", "created_by"),
            ("episode", "created_by"),
            ("agent_session", "user_id"),
        ):
            table, col = table_col
            await session.execute(
                text(f"UPDATE {table} SET {col} = NULL WHERE {col} = :uid"),
                {"uid": user_id},
            )

        # BetterAuth tables — session/account cascade from `user`, so
        # deleting the BetterAuth user row is enough. BetterAuth stores
        # id as text (matching our uuid string via generateId: "uuid").
        await session.execute(
            text('DELETE FROM "user" WHERE id = :uid'),
            {"uid": user_id},
        )
        await session.execute(
            text("DELETE FROM app_user WHERE id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        )
