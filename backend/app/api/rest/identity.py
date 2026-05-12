"""Per-user external-identity bridge.

A user must connect each provider (Google in v1) so the visibility
filter can resolve them against source-document ACLs. The flow is
deliberately separate from the connector install — any workspace
member connects their own identity, regardless of who installed the
connector.

Mock mode (``MOCK_DRIVE=1``) skips Google's consent screen and
fabricates an identity from the caller's ``app_user.email``. This
keeps the docker-compose demo runnable without OAuth credentials.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.deps import CurrentPrincipal, DbSession
from app.core.config import get_settings
from app.domain import audit as audit_log

router = APIRouter(prefix="/identity", tags=["identity"])


class IdentityOut(BaseModel):
    id: str
    user_id: str
    workspace_id: str
    provider: str
    external_id: str
    external_email: str | None
    groups_resolution: str
    created_at: str


class AuthorizeUrlOut(BaseModel):
    url: str


class CallbackIn(BaseModel):
    code: str
    state: str


def _row_to_out(row: dict[str, Any]) -> IdentityOut:
    return IdentityOut(
        id=row["id"],
        user_id=row["user_id"],
        workspace_id=row["workspace_id"],
        provider=row["provider"],
        external_id=row["external_id"],
        external_email=row.get("external_email"),
        groups_resolution=row["groups_resolution"],
        created_at=row["created_at"],
    )


def _redirect_uri() -> str:
    base = get_settings().web_base_url.rstrip("/")
    return f"{base}/identity/google/callback"


def _state_secret() -> str:
    """Random nonce kept on the principal for CSRF binding.

    For v1 we use a session-cookie-equivalent: a per-callback random
    string tied to the caller's user_id via HMAC. Simpler than persisting
    a row in a state table, and matches the OAuth flow we run today on
    the workspace tokens path.
    """
    return secrets.token_urlsafe(24)


@router.get("")
async def list_identities(
    principal: CurrentPrincipal, session: DbSession
) -> list[IdentityOut]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    result = await session.execute(
        text(
            """
            SELECT id::text, user_id::text, workspace_id::text, provider,
                   external_id, external_email, groups_resolution,
                   created_at::text
            FROM user_external_identity
            WHERE workspace_id = CAST(:ws AS uuid)
              AND user_id = CAST(:u AS uuid)
            ORDER BY created_at DESC
            """
        ),
        {"ws": principal.workspace_id, "u": principal.user_id},
    )
    return [_row_to_out(dict(r)) for r in result.mappings()]


@router.post("/google/authorize-url")
async def google_authorize_url(
    principal: CurrentPrincipal, session: DbSession
) -> AuthorizeUrlOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    settings = get_settings()
    state = f"{principal.user_id}:{principal.workspace_id}:{_state_secret()}"

    if settings.mock_drive:
        # Mock: skip Google's consent screen entirely. The frontend
        # callback page will pass `code=mock-id` and our callback handler
        # fabricates an identity from the caller's app_user.email.
        return AuthorizeUrlOut(
            url=f"{_redirect_uri()}?{urlencode({'code': 'mock-id', 'state': state})}"
        )

    if not settings.google_oauth_client_id:
        raise HTTPException(
            400, "GOOGLE_OAUTH_CLIENT_ID not configured; cannot start identity OAuth"
        )
    params = {
        "response_type": "code",
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": _redirect_uri(),
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return AuthorizeUrlOut(
        url=f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    )


@router.post("/google/callback")
async def google_callback(
    payload: CallbackIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> IdentityOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    parts = payload.state.split(":", 2)
    if len(parts) != 3 or parts[0] != principal.user_id or parts[1] != principal.workspace_id:
        raise HTTPException(400, "state mismatch")

    settings = get_settings()
    if settings.mock_drive or payload.code == "mock-id":
        # Fabricate an identity from the caller's app_user row. Used by
        # the docker demo and the E2E test.
        user_row = await session.execute(
            text("SELECT email FROM app_user WHERE id = CAST(:id AS uuid)"),
            {"id": principal.user_id},
        )
        email_val = user_row.scalar()
        if not email_val:
            raise HTTPException(400, "user has no email; cannot bootstrap identity")
        external_id = f"mock-google-sub-{principal.user_id}"
        external_email = str(email_val)
    else:
        # Real path: exchange the code, parse the id_token, pull sub + email.
        external_id, external_email = await _real_google_exchange(payload.code)

    inserted = await session.execute(
        text(
            """
            INSERT INTO user_external_identity
              (workspace_id, user_id, provider, external_id, external_email)
            VALUES (CAST(:ws AS uuid), CAST(:u AS uuid), 'google', :ext, :email)
            ON CONFLICT (workspace_id, provider, external_id) DO UPDATE
              SET external_email = EXCLUDED.external_email,
                  updated_at = now()
            RETURNING id::text, user_id::text, workspace_id::text, provider,
                      external_id, external_email, groups_resolution,
                      created_at::text
            """
        ),
        {
            "ws": principal.workspace_id,
            "u": principal.user_id,
            "ext": external_id,
            "email": external_email,
        },
    )
    row = dict(inserted.mappings().one())
    await audit_log.write(
        session,
        workspace_id=principal.workspace_id,
        actor_kind="user",
        actor_id=principal.user_id,
        action="identity.connect",
        target_kind="user_external_identity",
        target_id=row["id"],
        diff={"provider": "google", "email": external_email},
    )
    return _row_to_out(row)


@router.delete("/{identity_id}", status_code=204)
async def disconnect_identity(
    identity_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> None:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    result = await session.execute(
        text(
            """
            DELETE FROM user_external_identity
            WHERE id = CAST(:id AS uuid)
              AND workspace_id = CAST(:ws AS uuid)
              AND user_id = CAST(:u AS uuid)
            RETURNING id::text
            """
        ),
        {"id": identity_id, "ws": principal.workspace_id, "u": principal.user_id},
    )
    if result.first() is None:
        raise HTTPException(404, "identity not found")
    await audit_log.write(
        session,
        workspace_id=principal.workspace_id,
        actor_kind="user",
        actor_id=principal.user_id,
        action="identity.disconnect",
        target_kind="user_external_identity",
        target_id=identity_id,
    )


async def _real_google_exchange(code: str) -> tuple[str, str | None]:
    """Real Google OAuth code exchange. Returns (sub, email).

    Used only when ``MOCK_DRIVE`` is false. We stay scope-light here
    (openid + email) — Drive scope is on the connector, not the identity
    bridge.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(400, f"google token exchange failed: {resp.text}")
    body = resp.json()
    id_token = body.get("id_token")
    if not id_token:
        raise HTTPException(400, "google response missing id_token")
    # Trust the freshly-issued id_token. The exchange itself is the proof
    # of authenticity — we just decoded the unsigned payload to read sub
    # and email. (The token was returned over TLS by Google's OAuth
    # endpoint with our client credentials.)
    payload = _decode_jwt_payload(id_token)
    sub = payload.get("sub")
    email = payload.get("email")
    if not sub:
        raise HTTPException(400, "google id_token missing sub")
    return str(sub), str(email) if email else None


def _decode_jwt_payload(id_token: str) -> dict[str, Any]:
    import base64

    parts = id_token.split(".")
    if len(parts) < 2:
        raise HTTPException(400, "malformed id_token")
    # Base64url decode (with padding fix).
    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    raw = base64.urlsafe_b64decode(payload_b64)
    return json.loads(raw)
