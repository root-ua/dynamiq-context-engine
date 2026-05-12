"""Agent bearer tokens — create, verify, list, revoke.

Tokens look like ``mem_<32-url-safe-chars>``. The ``mem_`` prefix makes
them scannable in git-secret scanners and server logs. The full token is
argon2-hashed at rest; only a short ``prefix`` column (first 8 chars of
the random tail) is stored in plaintext so the UI can show *something* to
identify each row. The plaintext is shown to the user exactly once at
creation time.

Verification is O(1): parse the prefix out of the submitted token, fetch
candidate rows by that prefix, argon2-verify one. Argon2 is deliberately
expensive, so a large workspace with many tokens still only pays one
hash.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_scope

TOKEN_PREFIX = "mem_"
PREFIX_LEN = 8  # chars after `mem_` we keep in plaintext for UI display


@dataclass
class AgentTokenRow:
    id: str
    workspace_id: str
    user_id: str
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: str | None
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    kind: str = "service"


@dataclass
class CreatedToken:
    row: AgentTokenRow
    token: str  # plaintext, shown once


_hasher = PasswordHasher()


def _generate_token() -> tuple[str, str]:
    """Return (plaintext_token, prefix)."""
    body = secrets.token_urlsafe(32)
    token = f"{TOKEN_PREFIX}{body}"
    # Prefix is first 8 chars of the random body (not the static "mem_").
    return token, body[:PREFIX_LEN]


def _row_to_dataclass(row: dict[str, Any]) -> AgentTokenRow:
    return AgentTokenRow(
        id=row["id"],
        workspace_id=row["workspace_id"],
        user_id=row["user_id"],
        name=row["name"],
        prefix=row["prefix"],
        scopes=list(row["scopes"] or []),
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        kind=row.get("kind", "service"),
    )


async def create_token(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    name: str,
    kind: str = "service",
    expires_at: datetime | None = None,
    scopes: list[str] | None = None,
) -> CreatedToken:
    if kind not in ("user", "service"):
        raise ValueError(f"invalid token kind: {kind!r}")
    token, prefix = _generate_token()
    token_hash = _hasher.hash(token)
    result = await session.execute(
        text(
            """
            INSERT INTO agent_token (
              workspace_id, user_id, name, prefix, token_hash, scopes, expires_at, kind
            ) VALUES (
              CAST(:workspace_id AS uuid),
              CAST(:user_id AS uuid),
              :name, :prefix, :token_hash,
              COALESCE(:scopes, ARRAY['mcp']::text[]),
              :expires_at,
              :kind
            )
            RETURNING id::text, workspace_id::text, user_id::text, name, prefix,
                      scopes, last_used_at::text, created_at::text,
                      expires_at::text, revoked_at::text, kind
            """
        ),
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "name": name,
            "prefix": prefix,
            "token_hash": token_hash,
            "scopes": scopes,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "kind": kind,
        },
    )
    row = result.mappings().one()
    return CreatedToken(row=_row_to_dataclass(dict(row)), token=token)


async def list_tokens(
    session: AsyncSession, *, workspace_id: str
) -> list[AgentTokenRow]:
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, user_id::text, name, prefix,
                   scopes, last_used_at::text, created_at::text,
                   expires_at::text, revoked_at::text, kind
            FROM agent_token
            WHERE workspace_id = CAST(:ws AS uuid)
            ORDER BY created_at DESC
            """
        ),
        {"ws": workspace_id},
    )
    return [_row_to_dataclass(dict(r)) for r in result.mappings()]


async def revoke_token(
    session: AsyncSession, *, workspace_id: str, token_id: str
) -> bool:
    result = await session.execute(
        text(
            """
            UPDATE agent_token
            SET revoked_at = now()
            WHERE id = CAST(:id AS uuid)
              AND workspace_id = CAST(:ws AS uuid)
              AND revoked_at IS NULL
            RETURNING id::text
            """
        ),
        {"id": token_id, "ws": workspace_id},
    )
    return result.rowcount > 0


@dataclass
class VerifiedToken:
    workspace_id: str
    user_id: str
    token_id: str
    scopes: list[str]
    kind: str  # 'user' | 'service' — drives Principal.kind at the auth layer


async def verify_token(token: str) -> VerifiedToken | None:
    """Resolve a `mem_...` token to a VerifiedToken.

    Runs outside the request's workspace-scoped session because the caller
    hasn't picked a workspace yet — we're *resolving* one from the token.
    Uses session_scope() without RLS vars so the lookup hits every row.

    Expired and revoked rows are filtered *before* argon2-verify so a
    compromised-but-expired token doesn't pay the CPU cost on every probe
    and can't be used as a CPU-exhaustion oracle.
    """
    if not token.startswith(TOKEN_PREFIX):
        return None
    body = token[len(TOKEN_PREFIX) :]
    if len(body) < PREFIX_LEN:
        return None
    prefix = body[:PREFIX_LEN]

    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, user_id::text, token_hash,
                       expires_at, revoked_at, scopes, kind
                FROM agent_token
                WHERE prefix = :prefix
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > now())
                """
            ),
            {"prefix": prefix},
        )
        candidates = list(result.mappings())
        verified: VerifiedToken | None = None
        for row in candidates:
            try:
                _hasher.verify(row["token_hash"], token)
            except VerifyMismatchError:
                continue
            verified = VerifiedToken(
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                token_id=row["id"],
                scopes=list(row["scopes"] or []),
                kind=row["kind"],
            )
            break

        if verified is None:
            return None

        # Best-effort bump of last_used_at. Inside the same session so it
        # commits with the rest of the lookup — fine because this write is
        # tiny and idempotent.
        await session.execute(
            text(
                "UPDATE agent_token SET last_used_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": verified.token_id},
        )
        return verified
