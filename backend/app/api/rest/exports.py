"""Workspace + user data export endpoints.

POST   /api/workspaces/:id/export            (admin/owner) → enqueues job, returns row
GET    /api/workspaces/:id/export/:job_id    → polls; download_url fresh-presigned
POST   /api/me/export                        → user-scoped GDPR dump
GET    /api/me/export/:job_id                → polls user dump

The actual heavy lifting runs in ``app.workers.export``; this module
only enqueues and reads back.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.auth.deps import CurrentPrincipal, DbSession, require_workspace_role
from app.workers.export import fresh_presigned_url
from app.workers.queue import enqueue_user_export, enqueue_workspace_export

router = APIRouter()

# ---------------------------------------------------------------------------
# /api/workspaces/:id/export
# ---------------------------------------------------------------------------

workspace_router = APIRouter(prefix="/workspaces", tags=["exports"])


@workspace_router.post("/{workspace_id}/export", status_code=201)
async def start_workspace_export(
    workspace_id: str,
    session: DbSession,
    principal=Depends(require_workspace_role("admin", "owner")),
) -> dict[str, Any]:
    if principal.workspace_id != workspace_id:
        raise HTTPException(403, "wrong workspace")
    row = (
        await session.execute(
            text(
                """
                INSERT INTO export_job
                  (workspace_id, requester_user_id, scope, status)
                VALUES (:ws, :uid, 'workspace', 'queued')
                RETURNING id::text, workspace_id::text, scope, status,
                          object_key, byte_size,
                          download_expires_at::text, error_message,
                          created_at::text, completed_at::text
                """
            ),
            {"ws": workspace_id, "uid": principal.user_id},
        )
    ).mappings().first()
    assert row is not None
    await enqueue_workspace_export(
        job_id=row["id"], workspace_id=workspace_id
    )
    return _shape(dict(row))


@workspace_router.get("/{workspace_id}/export/{job_id}")
async def poll_workspace_export(
    workspace_id: str,
    job_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, Any]:
    if principal.workspace_id != workspace_id:
        raise HTTPException(403, "wrong workspace")
    row = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, scope, status,
                       object_key, byte_size,
                       download_expires_at::text, error_message,
                       created_at::text, completed_at::text
                FROM export_job
                WHERE id = :id AND scope = 'workspace'
                """
            ),
            {"id": job_id},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(404, "export job not found")
    return _shape(dict(row))


# ---------------------------------------------------------------------------
# /api/me/export
# ---------------------------------------------------------------------------

me_router = APIRouter(prefix="/me", tags=["exports"])


@me_router.post("/export", status_code=201)
async def start_user_export(
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, Any]:
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot request user exports")
    row = (
        await session.execute(
            text(
                """
                INSERT INTO export_job
                  (workspace_id, requester_user_id, scope, status)
                VALUES (NULL, :uid, 'user', 'queued')
                RETURNING id::text, workspace_id::text, scope, status,
                          object_key, byte_size,
                          download_expires_at::text, error_message,
                          created_at::text, completed_at::text
                """
            ),
            {"uid": principal.user_id},
        )
    ).mappings().first()
    assert row is not None
    await enqueue_user_export(job_id=row["id"], user_id=principal.user_id)
    return _shape(dict(row))


@me_router.get("/export/{job_id}")
async def poll_user_export(
    job_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, scope, status,
                       object_key, byte_size,
                       download_expires_at::text, error_message,
                       created_at::text, completed_at::text,
                       requester_user_id::text AS requester_user_id
                FROM export_job
                WHERE id = :id AND scope = 'user'
                """
            ),
            {"id": job_id},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(404, "export job not found")
    if row["requester_user_id"] != principal.user_id:
        raise HTTPException(403, "not your export")
    return _shape(dict(row))


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _shape(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "workspace_id": row.get("workspace_id"),
        "scope": row["scope"],
        "status": row["status"],
        "object_key": row.get("object_key"),
        "byte_size": row.get("byte_size"),
        "download_url": None,
        "download_expires_at": row.get("download_expires_at"),
        "error_message": row.get("error_message"),
        "created_at": row["created_at"],
        "completed_at": row.get("completed_at"),
    }
    if row.get("status") == "completed" and row.get("object_key"):
        try:
            out["download_url"] = fresh_presigned_url(row["object_key"])
        except Exception:
            # If MinIO isn't reachable the caller still gets the row;
            # they can poll again.
            out["download_url"] = None
    return out


router.include_router(workspace_router)
router.include_router(me_router)
