from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import jwt

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class AuthError(Exception):
    pass


PrincipalKind = Literal["user", "service"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str | None
    workspace_id: str | None
    role: str | None
    claims: dict[str, Any]
    # 'user': real human caller — the per-source ACL filter applies.
    # 'service': workspace service-account caller (e.g. crawler worker) —
    # bypasses the ACL filter and relies on workspace RLS only. Session
    # JWTs are always 'user'; agent tokens carry the kind in their row.
    kind: PrincipalKind = "user"


def decode_token(token: str) -> Principal:
    """Verify an HS256 session JWT and return the principal.

    `aud` is REQUIRED and must match our canonical MCP resource URL per
    RFC 8707 — this binds tokens to this resource server and prevents
    a JWT minted for another service from being replayed here.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.mcp_resource_url,
            options={
                "require": ["exp", "sub", "aud"],
                "verify_aud": True,
            },
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc

    return Principal(
        user_id=str(claims["sub"]),
        email=claims.get("email"),
        workspace_id=claims.get("workspace_id"),
        role=claims.get("role"),
        claims=claims,
    )
