"""DB access for Google Drive integration tables.

Wraps:
- ``google_drive_connection``      — OAuth tokens (encrypted at rest).
- ``user_external_identity``       — user_id ↔ google email mapping.
- ``google_doc_sync_state``        — per-doc sync ledger (dedup + status).
- ``episode_external_acl``         — per-episode Drive permission projection.
- ``google_docs_sync_job``         — one row per "Sync now" click (UI progress).

Encryption happens at the API of this module — callers pass plaintext tokens,
the helpers encrypt before INSERT and decrypt after SELECT. Callers should
never touch the `bytea` columns directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import decrypt, encrypt
from app.integrations.google.drive_client import DrivePermission


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GoogleDriveConnection:
    id: str
    workspace_id: str
    user_id: str
    account_email: str
    access_token: str           # decrypted in-memory only
    refresh_token: str          # decrypted in-memory only
    expires_at: datetime
    scopes: list[str]
    selection: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


@dataclass
class GoogleDriveConnectionSummary:
    """Connection view safe to return to UI — no tokens."""
    id: str
    workspace_id: str
    user_id: str
    account_email: str
    scopes: list[str]
    selection: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None

    @classmethod
    def from_connection(cls, c: GoogleDriveConnection) -> "GoogleDriveConnectionSummary":
        return cls(
            id=c.id, workspace_id=c.workspace_id, user_id=c.user_id,
            account_email=c.account_email, scopes=c.scopes,
            selection=c.selection, created_at=c.created_at,
            updated_at=c.updated_at, revoked_at=c.revoked_at,
        )


@dataclass
class SyncJob:
    id: str
    workspace_id: str
    connection_id: str
    triggered_by: str | None
    status: str
    total_docs: int
    processed_docs: int
    failed_docs: int
    skipped_docs: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass
class DocSyncState:
    id: str
    workspace_id: str
    connection_id: str
    google_doc_id: str
    doc_title: str | None
    doc_modified_at: datetime | None
    content_hash: str | None
    episode_id: str | None
    status: str
    error: str | None
    last_synced_at: datetime | None


# ---------------------------------------------------------------------------
# Connection CRUD
# ---------------------------------------------------------------------------


async def upsert_connection(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    account_email: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
    scopes: list[str],
) -> str:
    """Insert or refresh a connection. Returns connection id."""
    connection_id = str(uuid4())
    enc_access = encrypt(access_token)
    enc_refresh = encrypt(refresh_token)
    row = await session.execute(
        text(
            """
            INSERT INTO google_drive_connection
              (id, workspace_id, user_id, account_email,
               oauth_access_token, oauth_refresh_token, oauth_expires_at, scopes)
            VALUES
              (:id, :workspace_id, :user_id, :account_email,
               :access, :refresh, :expires_at, :scopes)
            ON CONFLICT (workspace_id, user_id, account_email)
            DO UPDATE SET
              oauth_access_token = EXCLUDED.oauth_access_token,
              oauth_refresh_token = EXCLUDED.oauth_refresh_token,
              oauth_expires_at = EXCLUDED.oauth_expires_at,
              scopes = EXCLUDED.scopes,
              updated_at = now(),
              revoked_at = NULL
            RETURNING id::text
            """
        ),
        {
            "id": connection_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "account_email": account_email,
            "access": enc_access,
            "refresh": enc_refresh,
            "expires_at": expires_at,
            "scopes": scopes,
        },
    )
    return row.scalar_one()


async def get_connection(
    session: AsyncSession, *, workspace_id: str, connection_id: str
) -> GoogleDriveConnection | None:
    row = (await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, user_id::text, account_email,
                   oauth_access_token, oauth_refresh_token, oauth_expires_at,
                   scopes, selection, created_at, updated_at, revoked_at
            FROM google_drive_connection
            WHERE id = :id AND workspace_id = :ws
            """
        ),
        {"id": connection_id, "ws": workspace_id},
    )).mappings().first()
    if row is None:
        return None
    return _row_to_connection(row)


async def list_connections(
    session: AsyncSession, *, workspace_id: str, user_id: str | None = None
) -> list[GoogleDriveConnectionSummary]:
    if user_id:
        q = """
            SELECT id::text, workspace_id::text, user_id::text, account_email,
                   oauth_access_token, oauth_refresh_token, oauth_expires_at,
                   scopes, selection, created_at, updated_at, revoked_at
            FROM google_drive_connection
            WHERE workspace_id = :ws AND user_id = :user_id AND revoked_at IS NULL
            ORDER BY created_at DESC
        """
        params = {"ws": workspace_id, "user_id": user_id}
    else:
        q = """
            SELECT id::text, workspace_id::text, user_id::text, account_email,
                   oauth_access_token, oauth_refresh_token, oauth_expires_at,
                   scopes, selection, created_at, updated_at, revoked_at
            FROM google_drive_connection
            WHERE workspace_id = :ws AND revoked_at IS NULL
            ORDER BY created_at DESC
        """
        params = {"ws": workspace_id}
    rows = (await session.execute(text(q), params)).mappings().all()
    return [GoogleDriveConnectionSummary.from_connection(_row_to_connection(r)) for r in rows]


async def update_tokens(
    session: AsyncSession,
    *,
    connection_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    await session.execute(
        text(
            """
            UPDATE google_drive_connection
            SET oauth_access_token = :access,
                oauth_refresh_token = :refresh,
                oauth_expires_at = :expires_at,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": connection_id,
            "access": encrypt(access_token),
            "refresh": encrypt(refresh_token),
            "expires_at": expires_at,
        },
    )


async def set_selection(
    session: AsyncSession,
    *,
    workspace_id: str,
    connection_id: str,
    selection: dict[str, Any],
) -> None:
    await session.execute(
        text(
            """
            UPDATE google_drive_connection
            SET selection = CAST(:sel AS jsonb), updated_at = now()
            WHERE id = :id AND workspace_id = :ws
            """
        ),
        {"id": connection_id, "ws": workspace_id, "sel": _json(selection)},
    )


async def revoke_connection(
    session: AsyncSession, *, workspace_id: str, connection_id: str
) -> None:
    await session.execute(
        text(
            """
            UPDATE google_drive_connection
            SET revoked_at = now(), updated_at = now()
            WHERE id = :id AND workspace_id = :ws
            """
        ),
        {"id": connection_id, "ws": workspace_id},
    )


# ---------------------------------------------------------------------------
# User external identity
# ---------------------------------------------------------------------------


async def upsert_user_identity(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    email: str,
) -> None:
    """Record a verified Google email for a workspace user.

    Idempotent. Used at OAuth callback time so v2's ACL filter can later resolve
    "what google emails does this user own?".
    """
    domain = email.split("@", 1)[1] if "@" in email else ""
    await session.execute(
        text(
            """
            INSERT INTO user_external_identity
              (workspace_id, user_id, provider, email, domain)
            VALUES (:ws, :user_id, 'google', :email, :domain)
            ON CONFLICT (workspace_id, user_id, provider, email) DO NOTHING
            """
        ),
        {"ws": workspace_id, "user_id": user_id, "email": email, "domain": domain},
    )


# ---------------------------------------------------------------------------
# Sync job lifecycle
# ---------------------------------------------------------------------------


async def create_sync_job(
    session: AsyncSession,
    *,
    workspace_id: str,
    connection_id: str,
    triggered_by: str | None,
) -> str:
    job_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO google_docs_sync_job
              (id, workspace_id, connection_id, triggered_by, status)
            VALUES (:id, :ws, :conn, :user, 'queued')
            """
        ),
        {"id": job_id, "ws": workspace_id, "conn": connection_id, "user": triggered_by},
    )
    return job_id


async def mark_job_running(session: AsyncSession, *, job_id: str, total_docs: int) -> None:
    await session.execute(
        text(
            """
            UPDATE google_docs_sync_job
            SET status = 'running', started_at = now(), total_docs = :total
            WHERE id = :id
            """
        ),
        {"id": job_id, "total": total_docs},
    )


async def increment_job(
    session: AsyncSession,
    *,
    job_id: str,
    processed: int = 0,
    failed: int = 0,
    skipped: int = 0,
) -> None:
    await session.execute(
        text(
            """
            UPDATE google_docs_sync_job
            SET processed_docs = processed_docs + :p,
                failed_docs    = failed_docs + :f,
                skipped_docs   = skipped_docs + :s
            WHERE id = :id
            """
        ),
        {"id": job_id, "p": processed, "f": failed, "s": skipped},
    )


async def mark_job_finished(
    session: AsyncSession, *, job_id: str, status: str, error: str | None = None
) -> None:
    await session.execute(
        text(
            """
            UPDATE google_docs_sync_job
            SET status = :s, error = :e, completed_at = now()
            WHERE id = :id
            """
        ),
        {"id": job_id, "s": status, "e": error},
    )


async def get_sync_job(session: AsyncSession, *, workspace_id: str, job_id: str) -> SyncJob | None:
    row = (await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, connection_id::text,
                   triggered_by::text, status, total_docs, processed_docs,
                   failed_docs, skipped_docs, error,
                   created_at, started_at, completed_at
            FROM google_docs_sync_job
            WHERE id = :id AND workspace_id = :ws
            """
        ),
        {"id": job_id, "ws": workspace_id},
    )).mappings().first()
    if row is None:
        return None
    return SyncJob(**dict(row))


# ---------------------------------------------------------------------------
# Per-doc sync state
# ---------------------------------------------------------------------------


async def get_sync_state(
    session: AsyncSession, *, connection_id: str, google_doc_id: str
) -> DocSyncState | None:
    row = (await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, connection_id::text, google_doc_id,
                   doc_title, doc_modified_at, content_hash, episode_id::text,
                   status, error, last_synced_at
            FROM google_doc_sync_state
            WHERE connection_id = :c AND google_doc_id = :doc
            """
        ),
        {"c": connection_id, "doc": google_doc_id},
    )).mappings().first()
    if row is None:
        return None
    return DocSyncState(**dict(row))


async def upsert_sync_state(
    session: AsyncSession,
    *,
    workspace_id: str,
    connection_id: str,
    google_doc_id: str,
    doc_title: str | None,
    doc_modified_at: datetime | None,
    content_hash: str | None,
    episode_id: str | None,
    status: str,
    error: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO google_doc_sync_state
              (workspace_id, connection_id, google_doc_id, doc_title,
               doc_modified_at, content_hash, episode_id, status, error,
               last_synced_at)
            VALUES
              (:ws, :c, :doc, :title, :modified_at, :hash, :ep, :status, :err,
               CASE WHEN :status IN ('completed','skipped') THEN now() ELSE NULL END)
            ON CONFLICT (connection_id, google_doc_id) DO UPDATE SET
              doc_title       = EXCLUDED.doc_title,
              doc_modified_at = EXCLUDED.doc_modified_at,
              content_hash    = EXCLUDED.content_hash,
              episode_id      = COALESCE(EXCLUDED.episode_id, google_doc_sync_state.episode_id),
              status          = EXCLUDED.status,
              error           = EXCLUDED.error,
              last_synced_at  = COALESCE(EXCLUDED.last_synced_at, google_doc_sync_state.last_synced_at)
            """
        ),
        {
            "ws": workspace_id, "c": connection_id, "doc": google_doc_id,
            "title": doc_title, "modified_at": doc_modified_at,
            "hash": content_hash, "ep": episode_id, "status": status, "err": error,
        },
    )


async def list_sync_states_for_connection(
    session: AsyncSession, *, workspace_id: str, connection_id: str
) -> list[DocSyncState]:
    rows = (await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, connection_id::text, google_doc_id,
                   doc_title, doc_modified_at, content_hash, episode_id::text,
                   status, error, last_synced_at
            FROM google_doc_sync_state
            WHERE workspace_id = :ws AND connection_id = :c
            ORDER BY last_synced_at DESC NULLS LAST, doc_title
            """
        ),
        {"ws": workspace_id, "c": connection_id},
    )).mappings().all()
    return [DocSyncState(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Episode external ACL projection
# ---------------------------------------------------------------------------


async def replace_episode_acl(
    session: AsyncSession,
    *,
    workspace_id: str,
    episode_id: str,
    source_doc_id: str,
    permissions: list[DrivePermission],
) -> None:
    """Wipe and rewrite ACL rows for one episode based on the doc's current perms.

    v1 stores these but does NOT enforce them at retrieval. v2 turns on the
    visibility predicate documented in the plan.
    """
    await session.execute(
        text("DELETE FROM episode_external_acl WHERE episode_id = :ep"),
        {"ep": episode_id},
    )
    if not permissions:
        return
    rows: list[dict[str, Any]] = []
    for p in permissions:
        # Drive 'type' values: user|group|domain|anyone. Map straight through.
        ace_kind = p.type if p.type in ("user", "group", "domain", "anyone") else "user"
        domain = p.domain
        if ace_kind == "user" and not domain and p.email and "@" in p.email:
            # For user ACEs, derive the user's domain for fallback lookup.
            domain = p.email.split("@", 1)[1]
        rows.append({
            "ws": workspace_id,
            "ep": episode_id,
            "kind": ace_kind,
            "email": p.email,
            "domain": domain,
            "role": p.role,
            "doc": source_doc_id,
        })
    await session.execute(
        text(
            """
            INSERT INTO episode_external_acl
              (workspace_id, episode_id, ace_kind, email, domain, role,
               provider, source_doc_id)
            VALUES (:ws, :ep, :kind, :email, :domain, :role, 'google_drive', :doc)
            """
        ),
        rows,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _row_to_connection(row: Any) -> GoogleDriveConnection:
    return GoogleDriveConnection(
        id=row["id"],
        workspace_id=row["workspace_id"],
        user_id=row["user_id"],
        account_email=row["account_email"],
        access_token=decrypt(row["oauth_access_token"]),
        refresh_token=decrypt(row["oauth_refresh_token"]),
        expires_at=row["oauth_expires_at"],
        scopes=list(row.get("scopes") or []),
        selection=row.get("selection") or {"folders": [], "files": []},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revoked_at=row.get("revoked_at"),
    )


def _json(value: Any) -> str:
    import json as _json_mod
    return _json_mod.dumps(value)
