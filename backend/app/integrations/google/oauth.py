"""Google OAuth 2.0 authorization-code flow.

Standard "web server" flow:
1. ``build_authorize_url(state)`` returns the URL the browser is redirected to.
2. Google bounces back to ``GOOGLE_REDIRECT_URI?code=...&state=...``.
3. ``exchange_code(code)`` swaps the code for {access_token, refresh_token, expires_at}.
4. On each subsequent Drive API call, ``refresh_if_needed(...)`` refreshes when
   the access token is within 5 minutes of expiry.

State parameter: a short signed JWT minted by the router (workspace_id, user_id,
random nonce). Verified on callback; the nonce is one-shot in Redis to block
replay.

Scopes (v1):
- https://www.googleapis.com/auth/drive.readonly — list + read all Drive content the user can access
- https://www.googleapis.com/auth/userinfo.email — for account_email + identity mapping
- openid                                          — required by Google to return userinfo
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
)

# Refresh access token when it has < this many seconds of validity left.
REFRESH_LEEWAY = timedelta(minutes=5)


class GoogleOAuthError(RuntimeError):
    """Raised when Google rejects an OAuth request."""


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: datetime  # tz-aware UTC
    scopes: list[str]


@dataclass
class UserInfo:
    email: str
    email_verified: bool
    sub: str  # Google's stable user id


def _require_oauth_configured() -> tuple[str, str, str]:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret or not s.google_redirect_uri:
        raise GoogleOAuthError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID, "
            "GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI in .env."
        )
    return s.google_client_id, s.google_client_secret, s.google_redirect_uri


def build_authorize_url(
    *,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    login_hint: str | None = None,
) -> str:
    """Return the URL the browser should be redirected to."""
    client_id, _, redirect_uri = _require_oauth_configured()
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        # access_type=offline + prompt=consent ensures we get a refresh_token
        # even on re-consent. Without these, Google often omits it.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> TokenBundle:
    """Swap an authorization code for access + refresh tokens."""
    client_id, client_secret, redirect_uri = _require_oauth_configured()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code >= 400:
        raise GoogleOAuthError(
            f"Token exchange failed (HTTP {resp.status_code}): {resp.text[:400]}"
        )
    body: dict[str, Any] = resp.json()
    refresh = body.get("refresh_token")
    if not refresh:
        # Common cause: the user previously consented and Google didn't re-issue
        # one. Our authorize URL forces prompt=consent to avoid this, but flag
        # anyway so the router can surface a clear message.
        raise GoogleOAuthError(
            "Google did not return a refresh_token. The user may have a "
            "stale grant; revoke at https://myaccount.google.com/permissions "
            "and try again."
        )
    return _to_bundle(body, refresh_token=refresh)


async def refresh_access_token(refresh_token: str) -> TokenBundle:
    """Exchange a stored refresh_token for a fresh access_token."""
    client_id, client_secret, _ = _require_oauth_configured()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code >= 400:
        raise GoogleOAuthError(
            f"Token refresh failed (HTTP {resp.status_code}): {resp.text[:400]}"
        )
    body: dict[str, Any] = resp.json()
    # Refresh response usually omits refresh_token (the old one is still valid).
    return _to_bundle(body, refresh_token=refresh_token)


async def fetch_userinfo(access_token: str) -> UserInfo:
    """Return the connected Google account's email + verified flag."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise GoogleOAuthError(
            f"userinfo failed (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    body = resp.json()
    return UserInfo(
        email=body["email"],
        email_verified=bool(body.get("email_verified", False)),
        sub=body["sub"],
    )


def needs_refresh(expires_at: datetime) -> bool:
    """True if the access token is within REFRESH_LEEWAY of expiring."""
    return datetime.now(timezone.utc) + REFRESH_LEEWAY >= expires_at


def _to_bundle(body: dict[str, Any], *, refresh_token: str) -> TokenBundle:
    expires_in = int(body.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    scope_str = body.get("scope") or ""
    return TokenBundle(
        access_token=body["access_token"],
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=scope_str.split() if scope_str else list(DEFAULT_SCOPES),
    )
