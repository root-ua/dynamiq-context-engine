"""Connector REST endpoints — install, OAuth callback, list, resync, delete.

The install flow:

1. ``POST /api/connectors`` (admin/owner) creates a row with
   ``status='authorizing'`` and returns an OAuth ``authorize_url`` for
   the user's browser.
2. The user consents on Google's screen, which redirects back to the
   frontend ``/[workspace]/settings/integrations/connectors/new/callback``
   page with ``?code=...&state=<instance_id>``.
3. The frontend page POSTs to ``/api/connectors/{id}/oauth-callback``
   with ``{code, state}``. The backend exchanges the code, encrypts the
   resulting bundle into ``connector_instance``, kicks off
   ``crawl_initial``, and writes an audit log entry.

Soft-delete (``DELETE``) sets ``deleted_at`` rather than dropping rows;
this preserves the bi-temporal episodes the connector ingested. Workers
refuse to crawl soft-deleted instances.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import (
    CurrentPrincipal,
    DbSession,
    require_workspace_role,
)
from app.connectors import registry
from app.connectors.base import CredentialBundle
from app.core.config import get_settings
from app.domain import audit as audit_log
from app.domain import connector as connector_domain
from app.workers.queue import enqueue_crawl_initial

router = APIRouter(prefix="/connectors", tags=["connectors"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConnectorOut(BaseModel):
    id: str
    workspace_id: str
    connector_kind: str
    display_name: str
    config: dict[str, Any]
    status: str
    last_full_crawl_at: str | None
    last_incremental_at: str | None
    last_error: str | None
    has_credentials: bool
    created_by: str
    created_at: str


class ConnectorCreateIn(BaseModel):
    kind: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=120)
    config: dict[str, Any] | None = None


class ConnectorCreateOut(BaseModel):
    instance: ConnectorOut
    authorize_url: str


class OAuthCallbackIn(BaseModel):
    code: str
    state: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _row_to_out(row: connector_domain.ConnectorInstanceRow) -> ConnectorOut:
    return ConnectorOut(
        id=row.id,
        workspace_id=row.workspace_id,
        connector_kind=row.connector_kind,
        display_name=row.display_name,
        config=row.config,
        status=row.status,
        last_full_crawl_at=row.last_full_crawl_at,
        last_incremental_at=row.last_incremental_at,
        last_error=row.last_error,
        has_credentials=row.has_credentials,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _redirect_uri() -> str:
    """Where Google sends the browser back after consent.

    Points at the frontend callback page so the React app can show
    progress / errors. The frontend page POSTs to our oauth-callback
    endpoint with the code + state.
    """
    base = get_settings().web_base_url.rstrip("/")
    return f"{base}/connectors/oauth-callback"


@router.get("")
async def list_connectors(
    principal: CurrentPrincipal,
    session: DbSession,
) -> list[ConnectorOut]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    rows = await connector_domain.list_active(
        session, workspace_id=principal.workspace_id
    )
    return [_row_to_out(r) for r in rows]


@router.post(
    "",
    status_code=201,
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def create_connector(
    payload: ConnectorCreateIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> ConnectorCreateOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    # Validate kind early so we don't create a row for an unknown connector.
    registry._import_connectors()
    try:
        cls = registry.get(payload.kind)
    except KeyError as exc:
        raise HTTPException(400, f"unknown connector kind: {payload.kind}") from exc

    row = await connector_domain.create(
        session,
        workspace_id=principal.workspace_id,
        connector_kind=payload.kind,
        display_name=payload.display_name,
        config=payload.config,
        created_by=principal.user_id,
    )

    # Audit
    await audit_log.write(
        session,
        workspace_id=principal.workspace_id,
        actor_kind="user",
        actor_id=principal.user_id,
        action="connector.create",
        target_kind="connector_instance",
        target_id=row.id,
        diff={"kind": payload.kind, "display_name": payload.display_name},
    )

    # Build the authorize URL. State is the instance id; the OAuth
    # callback re-validates that the row is in 'authorizing' state and
    # belongs to a workspace the caller administers.
    connector = cls()
    auth_url = await connector.authorize_url(
        instance_id=row.id,
        redirect_uri=_redirect_uri(),
        state=row.id,
    )

    return ConnectorCreateOut(instance=_row_to_out(row), authorize_url=auth_url)


@router.get("/{instance_id}")
async def get_connector(
    instance_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> ConnectorOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    row = await connector_domain.get(session, instance_id=instance_id)
    if not row or row.workspace_id != principal.workspace_id:
        raise HTTPException(404, "connector not found")
    return _row_to_out(row)


@router.delete(
    "/{instance_id}",
    status_code=204,
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def delete_connector(
    instance_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> None:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    row = await connector_domain.get(session, instance_id=instance_id)
    if not row or row.workspace_id != principal.workspace_id:
        raise HTTPException(404, "connector not found")
    ok = await connector_domain.soft_delete(session, instance_id=instance_id)
    if not ok:
        raise HTTPException(404, "connector not found or already deleted")
    await audit_log.write(
        session,
        workspace_id=principal.workspace_id,
        actor_kind="user",
        actor_id=principal.user_id,
        action="connector.delete",
        target_kind="connector_instance",
        target_id=instance_id,
        diff={"display_name": row.display_name},
    )


@router.post(
    "/{instance_id}/resync",
    dependencies=[Depends(require_workspace_role("owner", "admin"))],
)
async def resync_connector(
    instance_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, str]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    row = await connector_domain.get(session, instance_id=instance_id)
    if not row or row.workspace_id != principal.workspace_id:
        raise HTTPException(404, "connector not found")
    if row.status not in ("active", "error", "paused"):
        raise HTTPException(400, f"cannot resync from status={row.status}")
    # Reset to authorizing → active so the worker re-runs from scratch.
    await connector_domain.mark_status(
        session, instance_id=instance_id, status="active", error=None
    )
    await audit_log.write(
        session,
        workspace_id=principal.workspace_id,
        actor_kind="user",
        actor_id=principal.user_id,
        action="connector.resync",
        target_kind="connector_instance",
        target_id=instance_id,
        diff=None,
    )
    job_id = await enqueue_crawl_initial(connector_instance_id=instance_id)
    return {"job_id": job_id}


@router.post("/{instance_id}/oauth-callback")
async def oauth_callback(
    instance_id: str,
    payload: OAuthCallbackIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, Any]:
    """Exchange the OAuth code + persist credentials. Idempotent: if the
    connector is already active and we get a fresh code, we accept it
    (re-authorization)."""
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    if payload.state != instance_id:
        raise HTTPException(400, "state mismatch")

    row = await connector_domain.get(session, instance_id=instance_id)
    if not row or row.workspace_id != principal.workspace_id:
        raise HTTPException(404, "connector not found")

    registry._import_connectors()
    try:
        cls = registry.get(row.connector_kind)
    except KeyError as exc:
        raise HTTPException(500, f"connector kind disappeared: {row.connector_kind}") from exc
    connector = cls()
    try:
        bundle: CredentialBundle = await connector.exchange_code(
            instance_id=instance_id,
            code=payload.code,
            redirect_uri=_redirect_uri(),
        )
    except Exception as exc:  # noqa: BLE001
        await connector_domain.mark_status(
            session,
            instance_id=instance_id,
            status="error",
            error=f"oauth exchange: {exc}",
        )
        raise HTTPException(400, f"OAuth code exchange failed: {exc}") from exc

    await connector_domain.store_credentials(
        session, instance_id=instance_id, bundle=bundle
    )
    await audit_log.write(
        session,
        workspace_id=principal.workspace_id,
        actor_kind="user",
        actor_id=principal.user_id,
        action="connector.oauth.completed",
        target_kind="connector_instance",
        target_id=instance_id,
        diff={"by": principal.user_id},
    )
    job_id = await enqueue_crawl_initial(connector_instance_id=instance_id)
    return {"ok": True, "job_id": job_id}
