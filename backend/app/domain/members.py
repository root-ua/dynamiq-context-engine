"""Workspace members + invites.

Link-based invites: owner/admin generates a random token, shares the
resulting `/invite/<token>` URL, any authenticated user who visits that
URL is added to workspace_member at the preset role.

Role ladder: owner > admin > editor > viewer. Owner can do everything
including delete the workspace. Admin can manage members + content but
not delete the workspace. Editor can create/update content. Viewer is
read-only.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_ROLES = ("owner", "admin", "editor", "viewer")
ROLE_ORDER = {r: i for i, r in enumerate(VALID_ROLES)}


@dataclass
class Member:
    user_id: str
    email: str | None
    name: str | None
    role: str
    joined_at: str


@dataclass
class Invite:
    id: str
    workspace_id: str
    invited_email: str | None
    invited_by: str
    role: str
    token: str
    expires_at: str
    accepted_at: str | None
    revoked_at: str | None
    created_at: str


async def list_members(
    session: AsyncSession, *, workspace_id: str
) -> list[Member]:
    result = await session.execute(
        text(
            """
            SELECT m.user_id::text AS user_id,
                   u.email::text AS email,
                   u.name AS name,
                   m.role AS role,
                   m.joined_at::text AS joined_at
            FROM workspace_member m
            JOIN app_user u ON u.id = m.user_id
            WHERE m.workspace_id = CAST(:ws AS uuid)
            ORDER BY m.joined_at
            """
        ),
        {"ws": workspace_id},
    )
    return [Member(**dict(r)) for r in result.mappings()]


async def get_member_role(
    session: AsyncSession, *, workspace_id: str, user_id: str
) -> str | None:
    result = await session.execute(
        text(
            "SELECT role FROM workspace_member "
            "WHERE workspace_id = CAST(:ws AS uuid) "
            "AND user_id = CAST(:u AS uuid)"
        ),
        {"ws": workspace_id, "u": user_id},
    )
    row = result.first()
    return row[0] if row else None


async def update_member_role(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    role: str,
) -> bool:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role}")
    result = await session.execute(
        text(
            """
            UPDATE workspace_member
            SET role = :role
            WHERE workspace_id = CAST(:ws AS uuid)
              AND user_id = CAST(:u AS uuid)
            """
        ),
        {"ws": workspace_id, "u": user_id, "role": role},
    )
    return result.rowcount > 0


async def remove_member(
    session: AsyncSession, *, workspace_id: str, user_id: str
) -> bool:
    result = await session.execute(
        text(
            """
            DELETE FROM workspace_member
            WHERE workspace_id = CAST(:ws AS uuid)
              AND user_id = CAST(:u AS uuid)
            """
        ),
        {"ws": workspace_id, "u": user_id},
    )
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

async def create_invite(
    session: AsyncSession,
    *,
    workspace_id: str,
    invited_by: str,
    role: str,
    invited_email: str | None = None,
    ttl_days: int = 14,
) -> Invite:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role}")
    # Owner role can't be handed out via invite — owner transfer is a
    # separate, explicit action.
    if role == "owner":
        raise ValueError("owner role cannot be invited")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(tz=UTC) + timedelta(days=ttl_days)
    result = await session.execute(
        text(
            """
            INSERT INTO workspace_invite
              (workspace_id, invited_email, invited_by, role, token, expires_at)
            VALUES (
              CAST(:ws AS uuid), :email, CAST(:by AS uuid), :role, :token,
              :expires_at
            )
            RETURNING id::text, workspace_id::text, invited_email::text,
                      invited_by::text, role, token, expires_at::text,
                      accepted_at::text, revoked_at::text, created_at::text
            """
        ),
        {
            "ws": workspace_id,
            "email": invited_email,
            "by": invited_by,
            "role": role,
            "token": token,
            "expires_at": expires_at,
        },
    )
    return Invite(**dict(result.mappings().one()))


async def list_invites(
    session: AsyncSession, *, workspace_id: str, pending_only: bool = True
) -> list[Invite]:
    where = "workspace_id = CAST(:ws AS uuid)"
    if pending_only:
        where += " AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
    result = await session.execute(
        text(
            f"""
            SELECT id::text, workspace_id::text, invited_email::text,
                   invited_by::text, role, token, expires_at::text,
                   accepted_at::text, revoked_at::text, created_at::text
            FROM workspace_invite
            WHERE {where}
            ORDER BY created_at DESC
            """
        ),
        {"ws": workspace_id},
    )
    return [Invite(**dict(r)) for r in result.mappings()]


async def revoke_invite(
    session: AsyncSession, *, workspace_id: str, invite_id: str
) -> bool:
    result = await session.execute(
        text(
            """
            UPDATE workspace_invite
            SET revoked_at = now()
            WHERE id = CAST(:id AS uuid)
              AND workspace_id = CAST(:ws AS uuid)
              AND accepted_at IS NULL
              AND revoked_at IS NULL
            """
        ),
        {"id": invite_id, "ws": workspace_id},
    )
    return result.rowcount > 0


@dataclass
class InvitePreview:
    workspace_id: str
    workspace_slug: str
    workspace_name: str
    role: str
    invited_by_email: str | None
    invited_by_name: str | None
    invited_email: str | None


async def preview_invite(
    session: AsyncSession, *, token: str
) -> InvitePreview | None:
    """Fetch an invite's human-readable summary. Called from the accept
    page while the user is *not* yet a member — runs outside any RLS
    scope (session without workspace_id set).
    """
    result = await session.execute(
        text(
            """
            SELECT inv.workspace_id::text AS workspace_id,
                   w.slug AS workspace_slug,
                   w.name AS workspace_name,
                   inv.role AS role,
                   u.email::text AS invited_by_email,
                   u.name AS invited_by_name,
                   inv.invited_email::text AS invited_email
            FROM workspace_invite inv
            JOIN workspace w ON w.id = inv.workspace_id
            JOIN app_user u ON u.id = inv.invited_by
            WHERE inv.token = :token
              AND inv.accepted_at IS NULL
              AND inv.revoked_at IS NULL
              AND inv.expires_at > now()
              AND w.deleted_at IS NULL
            """
        ),
        {"token": token},
    )
    row = result.mappings().first()
    return InvitePreview(**dict(row)) if row else None


async def accept_invite(
    session: AsyncSession, *, token: str, user_id: str
) -> str | None:
    """Accept an invite. Returns the workspace_id on success, or None if
    the invite is bad (missing/expired/revoked) or the user is already a
    member.
    """
    # Fetch + lock the invite row.
    result = await session.execute(
        text(
            """
            SELECT id::text AS id, workspace_id::text AS workspace_id,
                   role AS role
            FROM workspace_invite
            WHERE token = :token
              AND accepted_at IS NULL
              AND revoked_at IS NULL
              AND expires_at > now()
            FOR UPDATE
            """
        ),
        {"token": token},
    )
    invite = result.mappings().first()
    if not invite:
        return None

    # If already a member, keep their existing role; just mark the invite
    # accepted so the link becomes single-use.
    existing_role = await get_member_role(
        session, workspace_id=invite["workspace_id"], user_id=user_id
    )
    if existing_role is None:
        await session.execute(
            text(
                """
                INSERT INTO workspace_member (workspace_id, user_id, role)
                VALUES (CAST(:ws AS uuid), CAST(:u AS uuid), :role)
                ON CONFLICT (workspace_id, user_id) DO NOTHING
                """
            ),
            {
                "ws": invite["workspace_id"],
                "u": user_id,
                "role": invite["role"],
            },
        )

    await session.execute(
        text(
            """
            UPDATE workspace_invite
            SET accepted_at = now(), accepted_by = CAST(:u AS uuid)
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": invite["id"], "u": user_id},
    )
    return invite["workspace_id"]


def _to_dict(obj: Any) -> dict[str, Any]:
    return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
