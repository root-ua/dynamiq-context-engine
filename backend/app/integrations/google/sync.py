"""Google Docs sync worker — the hot path.

Entry point: ``run_sync_job(ctx, job_id)``. Registered with Arq via
``backend/app/workers/jobs.py``.

Workflow per click of "Sync now":

1. Load the sync_job row + its connection + token bundle.
2. Resolve the user's selection (folders → all docs inside) into a flat doc id list.
3. For each doc (bounded concurrency):
   a. Fetch metadata + permissions (Drive API).
   b. If our last-synced content_hash matches Drive's head_revision_id → skip.
   c. Export plain text.
   d. Create an episode(source_kind='google-doc', source_ref=doc_id).
   e. Project Drive permissions into episode_external_acl (data captured for v2 ACL).
   f. Enqueue extract_episode so the existing pipeline takes over.
   g. Update sync_state + sync_job counters.
4. Mark the job completed.

All errors per-doc are caught and recorded; one bad doc doesn't kill the job.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.session import session_scope
from app.domain import episode as episode_mod
from app.domain import external_connection as ec
from app.integrations.google import oauth
from app.integrations.google.drive_client import (
    MIME_FOLDER,
    TEXT_EXTRACTABLE_MIMES,
    DriveAPIError,
    DriveClient,
)
from app.workers.queue import enqueue_extraction

logger = logging.getLogger(__name__)


SYNC_CONCURRENCY = 4


async def sync_google_docs(ctx: dict, *, job_id: str) -> dict[str, Any]:
    """Arq-compatible entry point. ``ctx`` is the worker context (unused)."""
    # 1. Open a session and load the job + connection together.
    async with session_scope() as session:
        job_row = await _load_job_or_die(session, job_id)
        workspace_id = job_row["workspace_id"]
        connection_id = job_row["connection_id"]
        connection = await ec.get_connection(session, workspace_id=workspace_id, connection_id=connection_id)
        if connection is None:
            await ec.mark_job_finished(session, job_id=job_id, status="failed",
                                       error="connection not found")
            await session.commit()
            return {"status": "failed", "error": "connection not found"}
        if connection.revoked_at is not None:
            await ec.mark_job_finished(session, job_id=job_id, status="failed",
                                       error="connection revoked")
            await session.commit()
            return {"status": "failed", "error": "connection revoked"}
        await session.commit()

    # 2. Refresh access token if needed and resolve the selection.
    access_token = await _refreshed_access_token(connection)
    selection = connection.selection or {"folders": [], "files": []}

    async with DriveClient(access_token) as drive:
        doc_ids = await _resolve_selection(drive, selection)

    # 3. Mark job running, then iterate docs with bounded concurrency.
    async with session_scope() as session:
        await ec.mark_job_running(session, job_id=job_id, total_docs=len(doc_ids))
        await session.commit()

    logger.info("google-sync.start", extra={"job_id": job_id, "total": len(doc_ids)})

    counters = {"processed": 0, "failed": 0, "skipped": 0}
    sem = asyncio.Semaphore(SYNC_CONCURRENCY)

    async def _one(doc_id: str) -> None:
        async with sem:
            result = await _sync_one_doc(
                workspace_id=workspace_id,
                connection_id=connection_id,
                connection_user_id=connection.user_id,
                access_token=access_token,
                doc_id=doc_id,
            )
            counters[result] = counters[result] + 1

    await asyncio.gather(*(_one(d) for d in doc_ids), return_exceptions=False)

    # 4. Finalize.
    async with session_scope() as session:
        await ec.mark_job_finished(session, job_id=job_id, status="completed")
        await session.commit()

    logger.info("google-sync.done", extra={"job_id": job_id, **counters})
    return {"status": "completed", **counters, "total": len(doc_ids)}


# ---------------------------------------------------------------------------
# Per-doc sync
# ---------------------------------------------------------------------------


async def _sync_one_doc(
    *,
    workspace_id: str,
    connection_id: str,
    connection_user_id: str,
    access_token: str,
    doc_id: str,
) -> str:
    """Sync one Google Doc into an episode. Returns 'processed' | 'failed' | 'skipped'."""
    try:
        async with DriveClient(access_token) as drive:
            meta = await drive.get_metadata(doc_id)

            # head_revision_id is Google-Docs-only; uploaded text files don't
            # have one. Fall back to modifiedTime so dedup still works.
            content_hash = _content_hash_for(meta)

            # Dedup by content_hash (head_revision_id or modifiedTime fallback).
            async with session_scope() as session:
                existing = await ec.get_sync_state(
                    session, connection_id=connection_id, google_doc_id=doc_id
                )
            if existing and content_hash is not None and existing.content_hash == content_hash:
                async with session_scope() as session:
                    await ec.upsert_sync_state(
                        session,
                        workspace_id=workspace_id,
                        connection_id=connection_id,
                        google_doc_id=doc_id,
                        doc_title=meta.name,
                        doc_modified_at=meta.modified_time,
                        content_hash=content_hash,
                        episode_id=existing.episode_id,
                        status="skipped",
                    )
                    await ec.increment_job(session, job_id=_NEEDS_JOB_ID_FROM_CTX, skipped=1) if False else None
                    await session.commit()
                # Counter incremented by caller via return value.
                return "skipped"

            # Pass the known mime so export_text can route without a second
            # metadata round-trip.
            text_body = await drive.export_text(doc_id, mime_type=meta.mime_type)
            if not text_body.strip():
                async with session_scope() as session:
                    await ec.upsert_sync_state(
                        session, workspace_id=workspace_id, connection_id=connection_id,
                        google_doc_id=doc_id, doc_title=meta.name,
                        doc_modified_at=meta.modified_time,
                        content_hash=content_hash, episode_id=None,
                        status="skipped", error="empty document",
                    )
                    await session.commit()
                return "skipped"

            body = f"# {meta.name}\n\n{text_body}" if meta.name else text_body

        # New transactional scope for the write side (after Drive I/O is done).
        async with session_scope() as session:
            episode = await episode_mod.add_episode(
                session,
                workspace_id=workspace_id,
                content=body,
                source_kind="google-doc",
                source_ref=doc_id,
                occurred_at=meta.modified_time,
                created_by=connection_user_id,
            )
            await ec.replace_episode_acl(
                session,
                workspace_id=workspace_id,
                episode_id=episode.id,
                source_doc_id=doc_id,
                permissions=meta.permissions,
            )
            await ec.upsert_sync_state(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                google_doc_id=doc_id,
                doc_title=meta.name,
                doc_modified_at=meta.modified_time,
                content_hash=content_hash,
                episode_id=episode.id,
                status="completed",
            )
            await session.commit()

        await enqueue_extraction(
            workspace_id=workspace_id,
            episode_id=episode.id,
            actor_id=connection_user_id,
        )
        return "processed"

    except DriveAPIError as e:
        logger.warning("google-sync.doc.failed", extra={"doc_id": doc_id, "error": str(e)})
        async with session_scope() as session:
            await ec.upsert_sync_state(
                session, workspace_id=workspace_id, connection_id=connection_id,
                google_doc_id=doc_id, doc_title=None, doc_modified_at=None,
                content_hash=None, episode_id=None, status="failed",
                error=f"drive: {e.message}",
            )
            await session.commit()
        return "failed"
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("google-sync.doc.unexpected", extra={"doc_id": doc_id})
        async with session_scope() as session:
            await ec.upsert_sync_state(
                session, workspace_id=workspace_id, connection_id=connection_id,
                google_doc_id=doc_id, doc_title=None, doc_modified_at=None,
                content_hash=None, episode_id=None, status="failed",
                error=str(exc),
            )
            await session.commit()
        return "failed"


# Sentinel used inside _sync_one_doc; the actual counter bump happens via the
# caller's `counters[result]` increment in `_one`. The duplicate increment_job
# call above is dead-code-guarded by `if False` — kept here to document the
# intent that v2 may want per-doc job-counter updates (cheaper one big update
# at end vs many small ones).
_NEEDS_JOB_ID_FROM_CTX = "n/a"


# ---------------------------------------------------------------------------
# Selection resolution
# ---------------------------------------------------------------------------


async def _resolve_selection(drive: DriveClient, selection: dict[str, Any]) -> list[str]:
    """Expand the user-saved selection into a flat list of Google Doc IDs.

    Selection shape (from the picker UI):
        {
          "folders": [{"id": "...", "name": "..."}, ...],
          "files":   [{"id": "...", "name": "..."}, ...]
        }
    """
    seen: set[str] = set()
    out: list[str] = []

    # Direct file picks.
    for f in selection.get("files") or []:
        fid = f.get("id")
        if fid and fid not in seen:
            seen.add(fid)
            out.append(fid)

    # Folder picks → recurse and collect google-doc children.
    for f in selection.get("folders") or []:
        fid = f.get("id")
        if not fid:
            continue
        async for doc_id in _iter_docs_in_folder(drive, folder_id=fid):
            if doc_id not in seen:
                seen.add(doc_id)
                out.append(doc_id)

    return out


async def _iter_docs_in_folder(drive: DriveClient, *, folder_id: str):
    """Async generator yielding all text-extractable file IDs under a folder."""
    stack = [folder_id]
    while stack:
        current = stack.pop()
        try:
            children = await drive.list_children(folder_id=current)
        except DriveAPIError as e:
            logger.warning("google-sync.folder.skip", extra={"folder_id": current, "error": str(e)})
            continue
        for c in children:
            if c.mime_type == MIME_FOLDER:
                stack.append(c.id)
            elif c.mime_type in TEXT_EXTRACTABLE_MIMES:
                yield c.id


def _content_hash_for(meta) -> str | None:
    """Pick the best content_hash for dedup.

    Google Docs expose headRevisionId — the canonical change marker. Uploaded
    text files don't, so we fall back to modifiedTime (ISO string). Either way
    we return a stable string the next sync can compare to.
    """
    if meta.head_revision_id:
        return meta.head_revision_id
    if meta.modified_time is not None:
        return meta.modified_time.isoformat()
    return None


# ---------------------------------------------------------------------------
# Token refresh + job loading
# ---------------------------------------------------------------------------


async def _refreshed_access_token(connection: ec.GoogleDriveConnection) -> str:
    """Return a fresh access token, refreshing via Google if needed.

    If refreshed, persist the new token to the DB so subsequent jobs can reuse it.
    """
    if not oauth.needs_refresh(connection.expires_at):
        return connection.access_token

    bundle = await oauth.refresh_access_token(connection.refresh_token)
    async with session_scope() as session:
        await ec.update_tokens(
            session,
            connection_id=connection.id,
            access_token=bundle.access_token,
            refresh_token=bundle.refresh_token,
            expires_at=bundle.expires_at,
        )
        await session.commit()
    return bundle.access_token


async def _load_job_or_die(session, job_id: str) -> dict[str, Any]:
    from sqlalchemy import text  # local import to keep top imports tidy
    row = (await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, connection_id::text, status,
                   total_docs, processed_docs, failed_docs, skipped_docs
            FROM google_docs_sync_job
            WHERE id = :id
            """
        ),
        {"id": job_id},
    )).mappings().first()
    if row is None:
        raise RuntimeError(f"google_docs_sync_job not found: {job_id}")
    return dict(row)
