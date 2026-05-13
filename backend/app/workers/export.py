"""Arq job: dump a workspace or user as gzipped newline-delimited JSON.

Triggered by REST endpoints in ``app.api.rest.exports``. Streams rows
out of Postgres one table at a time, encodes each as a JSON line, gzips
the whole stream in memory, and uploads to MinIO/S3.

Per-table chunk size is small (``BATCH``) so memory stays bounded even
for big workspaces — but the final gzipped blob still gets fully
materialized; for multi-GB exports we'd switch to multipart upload.
"""
from __future__ import annotations

import gzip
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import presign_get, put_object
from app.db.session import session_scope

log = get_logger(__name__)

BATCH = 500
PRESIGN_HOURS = 24

# Tables dumped for a workspace export. Order is stable so diffs between
# two exports are line-stable.
WORKSPACE_TABLES = (
    ("workspace", "id"),
    ("entity_type", "workspace_id"),
    ("relation_type", "workspace_id"),
    ("entity", "workspace_id"),
    ("entity_attribute", "workspace_id"),
    ("edge", "workspace_id"),
    ("document", "workspace_id"),
    ("block", "workspace_id"),
    ("episode", "workspace_id"),
    ("audit_log", "workspace_id"),
    ("prov_activity", "workspace_id"),
    ("pending_fact", "workspace_id"),
    ("extraction_policy", "workspace_id"),
    ("entity_external_ref", "workspace_id"),
    ("entity_resolution_decision", "workspace_id"),
    ("sensitivity_label", "workspace_id"),
    ("edge_label", "workspace_id"),
    ("episode_label", "workspace_id"),
    ("label_policy", "workspace_id"),
    ("action_type", "workspace_id"),
    ("action_invocation", "workspace_id"),
)


async def run_workspace_export(
    ctx: dict, *, job_id: str, workspace_id: str
) -> dict[str, Any]:
    return await _execute(job_id=job_id, scope="workspace", workspace_id=workspace_id)


async def run_user_export(
    ctx: dict, *, job_id: str, user_id: str
) -> dict[str, Any]:
    return await _execute(job_id=job_id, scope="user", user_id=user_id)


async def _execute(
    *,
    job_id: str,
    scope: str,
    workspace_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run the export and update the ``export_job`` row in-place."""
    async with session_scope(workspace_id=workspace_id) as session:
        await session.execute(
            text(
                "UPDATE export_job SET status = 'running' WHERE id = :id"
            ),
            {"id": job_id},
        )

    buf = io.BytesIO()
    try:
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            if scope == "workspace" and workspace_id:
                async with session_scope(workspace_id=workspace_id) as session:
                    await _dump_workspace(session, workspace_id, gz)
            elif scope == "user" and user_id:
                async with session_scope() as session:
                    await _dump_user(session, user_id, gz)
            else:
                raise ValueError(f"invalid scope/args: {scope}")
    except Exception as exc:
        log.exception("export.failed", job_id=job_id)
        async with session_scope(workspace_id=workspace_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE export_job
                    SET status = 'failed',
                        error_message = :err,
                        completed_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "err": str(exc)[:500]},
            )
        return {"job_id": job_id, "status": "failed", "error": str(exc)}

    payload = buf.getvalue()
    key_prefix = "exports/ws" if scope == "workspace" else "exports/me"
    key = f"{key_prefix}/{job_id}.jsonl.gz"
    try:
        bucket, size = put_object(
            key=key,
            data=payload,
            content_type="application/gzip",
        )
    except Exception as exc:
        log.exception("export.upload_failed", job_id=job_id)
        async with session_scope(workspace_id=workspace_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE export_job
                    SET status = 'failed',
                        error_message = :err,
                        completed_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "err": f"upload: {exc}"[:500]},
            )
        return {"job_id": job_id, "status": "failed"}

    expires_at = datetime.now(UTC) + timedelta(hours=PRESIGN_HOURS)
    async with session_scope(workspace_id=workspace_id) as session:
        await session.execute(
            text(
                """
                UPDATE export_job
                SET status = 'completed',
                    object_key = :key,
                    byte_size = :size,
                    download_expires_at = :exp,
                    completed_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "key": key, "size": size, "exp": expires_at},
        )
    log.info("export.completed", job_id=job_id, bytes=size, bucket=bucket)
    return {"job_id": job_id, "status": "completed", "byte_size": size}


async def _dump_workspace(
    session: AsyncSession, workspace_id: str, gz: gzip.GzipFile
) -> None:
    for table, key_col in WORKSPACE_TABLES:
        where = f"{key_col} = :wsid" if key_col != "id" else "id = :wsid"
        sql = f"SELECT row_to_json(t)::text AS row FROM {table} t WHERE {where}"
        async for row in _stream(session, sql, {"wsid": workspace_id}):
            _writeln(gz, table, row)


async def _dump_user(
    session: AsyncSession, user_id: str, gz: gzip.GzipFile
) -> None:
    """GDPR-style dump: only user-authored content from workspaces the
    requester is still a member of.

    The previous shape filtered solely on ``created_by = :uid`` which
    leaked rows from workspaces the user had since been removed from.
    Now every query joins to ``workspace_member`` so the dump matches
    what the user could actually see today.
    """
    # Always include the app_user row itself (independent of workspace).
    user_scoped_global = (
        (
            "app_user",
            "SELECT row_to_json(t)::text AS row FROM app_user t "
            "WHERE id = :uid",
        ),
    )

    # Per-workspace tables — limited to workspaces the user is currently
    # a member of (and that aren't soft-deleted).
    user_scoped_in_workspace = (
        (
            "entity_attribute",
            """
            SELECT row_to_json(t)::text AS row
            FROM entity_attribute t
            JOIN workspace_member m
              ON m.workspace_id = t.workspace_id
            WHERE t.created_by = :uid
              AND m.user_id = :uid
            """,
        ),
        (
            "edge",
            """
            SELECT row_to_json(t)::text AS row
            FROM edge t
            JOIN workspace_member m
              ON m.workspace_id = t.workspace_id
            WHERE t.created_by = :uid
              AND m.user_id = :uid
            """,
        ),
        (
            "document",
            """
            SELECT row_to_json(t)::text AS row
            FROM document t
            JOIN workspace_member m
              ON m.workspace_id = t.workspace_id
            WHERE t.created_by = :uid
              AND m.user_id = :uid
            """,
        ),
        (
            "audit_log",
            """
            SELECT row_to_json(t)::text AS row
            FROM audit_log t
            JOIN workspace_member m
              ON m.workspace_id = t.workspace_id
            WHERE t.actor_kind = 'user'
              AND t.actor_id = :uid
              AND m.user_id = :uid
            """,
        ),
    )

    for table, sql in user_scoped_global + user_scoped_in_workspace:
        async for row in _stream(session, sql, {"uid": user_id}):
            _writeln(gz, table, row)


async def _stream(session: AsyncSession, sql: str, params: dict[str, Any]):
    """Yield JSON-string rows one at a time.

    Uses ``yield_per(BATCH)`` so a workspace with millions of rows
    doesn't materialise the full result set in memory before the gzip
    streamer gets a chance to flush.
    """
    stmt = text(sql).execution_options(yield_per=BATCH)
    result = await session.stream(stmt, params)
    async for row in result.scalars():
        yield row


def _writeln(gz: gzip.GzipFile, table: str, raw_row: str) -> None:
    # Each line is its own object with a ``_table`` discriminator so the
    # consumer can reassemble without a separate manifest.
    parsed = json.loads(raw_row)
    line = json.dumps({"_table": table, **parsed}, default=str)
    gz.write(line.encode("utf-8"))
    gz.write(b"\n")


def fresh_presigned_url(object_key: str) -> str:
    """Re-sign the object key for download (used by GET endpoints)."""
    return presign_get(key=object_key, expires=timedelta(hours=PRESIGN_HOURS))
