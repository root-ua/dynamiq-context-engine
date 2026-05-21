"""Google Docs integration REST endpoints.

Mounted at ``/api/integrations/google-docs``.

User flow:
1. ``POST /authorize`` — backend mints a signed state JWT and returns the
   Google OAuth URL the frontend should redirect the browser to.
2. Browser visits Google, consents, lands on
   ``GET /callback?code=...&state=...``. We verify state, exchange the
   code, store the encrypted token + user identity, redirect back to the
   settings page.
3. ``GET /connections`` — list (sanitized).
4. ``GET /connections/{id}/tree`` — picker UI calls this per folder expand.
5. ``PUT /connections/{id}/selection`` — persist the user's selection.
6. ``POST /connections/{id}/sync`` — kick off an Arq sync_google_docs job.
7. ``GET /jobs/{id}`` + ``GET /connections/{id}/documents`` — progress UI.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, DbSession
from app.core.config import get_settings
from app.db.session import session_scope
from app.domain import external_connection as ec
from app.integrations.google import oauth
from app.integrations.google.drive_client import DriveClient, DriveAPIError
from app.workers.queue import get_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/google-docs", tags=["integrations:google-docs"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AuthorizeIn(BaseModel):
    # Where to send the user back in the SPA after OAuth completes.
    # Validated as a relative path on the same origin.
    return_to: str = Field(default="/settings/integrations/google-docs", max_length=400)


class AuthorizeOut(BaseModel):
    authorize_url: str


class ConnectionOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    account_email: str
    scopes: list[str]
    selection: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class ConnectionsOut(BaseModel):
    data: list[ConnectionOut]


class TreeNodeOut(BaseModel):
    id: str
    name: str
    mime_type: str
    is_folder: bool
    is_doc: bool


class TreeOut(BaseModel):
    parent: str
    children: list[TreeNodeOut]


class SelectionItem(BaseModel):
    id: str
    name: str


class SelectionIn(BaseModel):
    folders: list[SelectionItem] = Field(default_factory=list)
    files: list[SelectionItem] = Field(default_factory=list)


class SyncJobOut(BaseModel):
    id: str
    workspace_id: str
    connection_id: str
    status: str
    total_docs: int
    processed_docs: int
    failed_docs: int
    skipped_docs: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class SyncJobResponse(BaseModel):
    data: SyncJobOut


class DocStateOut(BaseModel):
    id: str
    google_doc_id: str
    doc_title: str | None
    status: str
    error: str | None
    episode_id: str | None
    last_synced_at: datetime | None


class DocsOut(BaseModel):
    data: list[DocStateOut]


# ---------------------------------------------------------------------------
# OAuth state signing
# ---------------------------------------------------------------------------


STATE_TTL = timedelta(minutes=15)
STATE_AUDIENCE = "google-docs-integration"


def _mint_state(*, workspace_id: str, user_id: str, return_to: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "return_to": return_to,
        "iat": int(now.timestamp()),
        "exp": int((now + STATE_TTL).timestamp()),
        "aud": STATE_AUDIENCE,
        "iss": s.jwt_issuer,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def _verify_state(state: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(
            state,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
            audience=STATE_AUDIENCE,
            issuer=s.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(400, f"invalid oauth state: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connection_to_dto(c: ec.GoogleDriveConnectionSummary) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        workspace_id=c.workspace_id,
        user_id=c.user_id,
        account_email=c.account_email,
        scopes=c.scopes,
        selection=c.selection,
        created_at=c.created_at,
        updated_at=c.updated_at,
        revoked_at=c.revoked_at,
    )


def _sync_job_to_dto(j: ec.SyncJob) -> SyncJobOut:
    return SyncJobOut(
        id=j.id,
        workspace_id=j.workspace_id,
        connection_id=j.connection_id,
        status=j.status,
        total_docs=j.total_docs,
        processed_docs=j.processed_docs,
        failed_docs=j.failed_docs,
        skipped_docs=j.skipped_docs,
        error=j.error,
        created_at=j.created_at,
        started_at=j.started_at,
        completed_at=j.completed_at,
    )


async def _refreshed_token_for_connection(
    session, *, connection: ec.GoogleDriveConnection
) -> str:
    if not oauth.needs_refresh(connection.expires_at):
        return connection.access_token
    bundle = await oauth.refresh_access_token(connection.refresh_token)
    await ec.update_tokens(
        session,
        connection_id=connection.id,
        access_token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        expires_at=bundle.expires_at,
    )
    return bundle.access_token


# ---------------------------------------------------------------------------
# OAuth start + callback
# ---------------------------------------------------------------------------


@router.post("/authorize", response_model=AuthorizeOut)
async def authorize(payload: AuthorizeIn, principal: CurrentPrincipal) -> AuthorizeOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    state = _mint_state(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        return_to=payload.return_to,
    )
    url = oauth.build_authorize_url(state=state)
    return AuthorizeOut(authorize_url=url)


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """OAuth redirect target. Verifies state, swaps code, persists connection.

    Auth: NO bearer token required — this is a top-level browser navigation
    from Google's redirect; there's no Authorization header to send. Identity
    instead comes from the signed ``state`` JWT minted by /authorize, which
    carries (workspace_id, user_id) and is audience-bound + short-lived so it
    can't be replayed elsewhere. We open a raw ``session_scope`` ourselves
    so this handler doesn't need ``DbSession`` (which would force auth).
    """
    web_base = get_settings().web_base_url.rstrip("/")
    if error:
        return RedirectResponse(
            url=f"{web_base}/settings/integrations/google-docs?error={error}",
            status_code=303,
        )
    claims = _verify_state(state)
    workspace_id = claims["workspace_id"]
    user_id = claims["user_id"]
    # Always build an absolute URL pointing at the web UI — the browser is
    # currently on the backend origin (localhost:8000) after Google's redirect.
    return_path = claims.get("return_to") or "/settings/integrations/google-docs"
    if not return_path.startswith("/"):
        return_path = "/" + return_path
    return_to = f"{web_base}{return_path}"

    try:
        bundle = await oauth.exchange_code(code)
        user = await oauth.fetch_userinfo(bundle.access_token)
    except oauth.GoogleOAuthError as exc:
        logger.warning("google-docs.oauth.failed", extra={"error": str(exc)})
        return RedirectResponse(url=f"{return_to}?error=oauth_failed", status_code=303)

    if not user.email_verified:
        return RedirectResponse(url=f"{return_to}?error=email_unverified", status_code=303)

    async with session_scope(workspace_id=workspace_id, user_id=user_id) as session:
        connection_id = await ec.upsert_connection(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            account_email=user.email,
            access_token=bundle.access_token,
            refresh_token=bundle.refresh_token,
            expires_at=bundle.expires_at,
            scopes=bundle.scopes,
        )
        await ec.upsert_user_identity(
            session, workspace_id=workspace_id, user_id=user_id, email=user.email
        )

    return RedirectResponse(
        url=f"{return_to}?connected=1&connection_id={connection_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Connections CRUD
# ---------------------------------------------------------------------------


@router.get("/connections", response_model=ConnectionsOut)
async def list_connections(
    principal: CurrentPrincipal, session: DbSession
) -> ConnectionsOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    items = await ec.list_connections(
        session, workspace_id=principal.workspace_id, user_id=principal.user_id
    )
    return ConnectionsOut(data=[_connection_to_dto(c) for c in items])


@router.delete("/connections/{connection_id}")
async def revoke_connection(
    connection_id: str, principal: CurrentPrincipal, session: DbSession
) -> dict[str, Any]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    await ec.revoke_connection(
        session, workspace_id=principal.workspace_id, connection_id=connection_id
    )
    return {"status": "revoked"}


# ---------------------------------------------------------------------------
# Picker + selection
# ---------------------------------------------------------------------------


@router.get("/connections/{connection_id}/tree", response_model=TreeOut)
async def tree(
    connection_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
    parent: str = Query(default="root"),
) -> TreeOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    conn = await ec.get_connection(
        session, workspace_id=principal.workspace_id, connection_id=connection_id
    )
    if conn is None or conn.revoked_at is not None:
        raise HTTPException(404, "connection not found")

    access_token = await _refreshed_token_for_connection(session, connection=conn)
    try:
        async with DriveClient(access_token) as drive:
            children = await drive.list_children(folder_id=parent)
    except DriveAPIError as exc:
        raise HTTPException(502, f"drive: {exc.message}")

    return TreeOut(
        parent=parent,
        children=[
            TreeNodeOut(
                id=c.id, name=c.name, mime_type=c.mime_type,
                is_folder=c.is_folder, is_doc=c.is_doc,
            )
            for c in children
        ],
    )


@router.put("/connections/{connection_id}/selection", response_model=ConnectionOut)
async def save_selection(
    connection_id: str,
    payload: SelectionIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> ConnectionOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    selection = {
        "folders": [s.model_dump() for s in payload.folders],
        "files": [s.model_dump() for s in payload.files],
    }
    await ec.set_selection(
        session,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
        selection=selection,
    )

    conn = await ec.get_connection(
        session, workspace_id=principal.workspace_id, connection_id=connection_id
    )
    if conn is None:
        raise HTTPException(404, "connection not found")
    return _connection_to_dto(ec.GoogleDriveConnectionSummary.from_connection(conn))


# ---------------------------------------------------------------------------
# Sync trigger + status
# ---------------------------------------------------------------------------


@router.post("/connections/{connection_id}/sync", response_model=SyncJobResponse, status_code=202)
async def start_sync(
    connection_id: str, principal: CurrentPrincipal, session: DbSession
) -> SyncJobResponse:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    conn = await ec.get_connection(
        session, workspace_id=principal.workspace_id, connection_id=connection_id
    )
    if conn is None or conn.revoked_at is not None:
        raise HTTPException(404, "connection not found")
    sel = conn.selection or {"folders": [], "files": []}
    if not sel.get("folders") and not sel.get("files"):
        raise HTTPException(400, "selection is empty — pick at least one folder or file first")

    job_id = await ec.create_sync_job(
        session,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
        triggered_by=principal.user_id,
    )

    queue = await get_queue()
    await queue.enqueue_job("sync_google_docs", job_id=job_id)

    job = await ec.get_sync_job(
        session, workspace_id=principal.workspace_id, job_id=job_id
    )
    assert job is not None
    return SyncJobResponse(data=_sync_job_to_dto(job))


@router.get("/jobs/{job_id}", response_model=SyncJobResponse)
async def get_job(
    job_id: str, principal: CurrentPrincipal, session: DbSession
) -> SyncJobResponse:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    job = await ec.get_sync_job(
        session, workspace_id=principal.workspace_id, job_id=job_id
    )
    if job is None:
        raise HTTPException(404, "job not found")
    return SyncJobResponse(data=_sync_job_to_dto(job))


@router.get("/connections/{connection_id}/documents", response_model=DocsOut)
async def list_documents(
    connection_id: str, principal: CurrentPrincipal, session: DbSession
) -> DocsOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    states = await ec.list_sync_states_for_connection(
        session, workspace_id=principal.workspace_id, connection_id=connection_id
    )
    return DocsOut(
        data=[
            DocStateOut(
                id=s.id,
                google_doc_id=s.google_doc_id,
                doc_title=s.doc_title,
                status=s.status,
                error=s.error,
                episode_id=s.episode_id,
                last_synced_at=s.last_synced_at,
            )
            for s in states
        ]
    )
