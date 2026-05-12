"""connector_instance CRUD + credential encryption.

Credentials live in ``connector_instance.credentials_encrypted`` as
pgcrypto pgp_sym_encrypt'd JSON. The symmetric key comes from settings;
``credentials_key_id`` lets us rotate by issuing tokens under a new key
and decrypting under the old one until backfill is done.

A connector is "active" once OAuth has produced a credential bundle and
``status`` flips from ``authorizing`` to ``active``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.connectors.base import CredentialBundle


class ConnectorError(Exception):
    pass


@dataclass
class ConnectorInstanceRow:
    id: str
    workspace_id: str
    connector_kind: str
    display_name: str
    config: dict[str, Any]
    status: str
    last_full_crawl_at: str | None
    last_incremental_at: str | None
    cursor: dict[str, Any] | None
    last_error: str | None
    created_by: str
    created_at: str
    deleted_at: str | None
    has_credentials: bool


def _row(row: dict[str, Any]) -> ConnectorInstanceRow:
    return ConnectorInstanceRow(
        id=row["id"],
        workspace_id=row["workspace_id"],
        connector_kind=row["connector_kind"],
        display_name=row["display_name"],
        config=dict(row["config"] or {}),
        status=row["status"],
        last_full_crawl_at=row["last_full_crawl_at"],
        last_incremental_at=row["last_incremental_at"],
        cursor=dict(row["cursor"]) if row.get("cursor") else None,
        last_error=row.get("last_error"),
        created_by=row["created_by"],
        created_at=row["created_at"],
        deleted_at=row.get("deleted_at"),
        has_credentials=bool(row.get("has_credentials")),
    )


_SELECT_FIELDS = """
  id::text, workspace_id::text, connector_kind, display_name, config,
  status, last_full_crawl_at::text, last_incremental_at::text,
  cursor, last_error, created_by::text, created_at::text, deleted_at::text,
  (credentials_encrypted IS NOT NULL) AS has_credentials
"""


async def create(
    session: AsyncSession,
    *,
    workspace_id: str,
    connector_kind: str,
    display_name: str,
    config: dict[str, Any] | None,
    created_by: str,
) -> ConnectorInstanceRow:
    result = await session.execute(
        text(
            f"""
            INSERT INTO connector_instance
              (workspace_id, connector_kind, display_name, config, created_by, status)
            VALUES (
              CAST(:ws AS uuid), :kind, :name,
              COALESCE(CAST(:cfg AS jsonb), '{{}}'::jsonb),
              CAST(:by AS uuid), 'authorizing'
            )
            RETURNING {_SELECT_FIELDS}
            """
        ),
        {
            "ws": workspace_id,
            "kind": connector_kind,
            "name": display_name,
            "cfg": json.dumps(config) if config else None,
            "by": created_by,
        },
    )
    return _row(dict(result.mappings().one()))


async def list_active(
    session: AsyncSession, *, workspace_id: str
) -> list[ConnectorInstanceRow]:
    result = await session.execute(
        text(
            f"""
            SELECT {_SELECT_FIELDS}
            FROM connector_instance
            WHERE workspace_id = CAST(:ws AS uuid) AND deleted_at IS NULL
            ORDER BY created_at DESC
            """
        ),
        {"ws": workspace_id},
    )
    return [_row(dict(r)) for r in result.mappings()]


async def get(
    session: AsyncSession, *, instance_id: str
) -> ConnectorInstanceRow | None:
    result = await session.execute(
        text(
            f"""
            SELECT {_SELECT_FIELDS}
            FROM connector_instance
            WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL
            """
        ),
        {"id": instance_id},
    )
    row = result.mappings().first()
    return _row(dict(row)) if row else None


async def soft_delete(
    session: AsyncSession, *, instance_id: str
) -> bool:
    result = await session.execute(
        text(
            """
            UPDATE connector_instance
            SET deleted_at = now(), status = 'inactive'
            WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL
            RETURNING id::text
            """
        ),
        {"id": instance_id},
    )
    return result.first() is not None


async def update_cursor(
    session: AsyncSession,
    *,
    instance_id: str,
    cursor: dict[str, Any] | None,
    incremental: bool,
) -> None:
    """Persist the connector's resume cursor and stamp the corresponding
    last-crawl-at timestamp."""
    field = "last_incremental_at" if incremental else "last_full_crawl_at"
    await session.execute(
        text(
            f"""
            UPDATE connector_instance
            SET cursor = CAST(:cur AS jsonb),
                {field} = now(),
                updated_at = now()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": instance_id, "cur": json.dumps(cursor) if cursor is not None else None},
    )


async def mark_status(
    session: AsyncSession,
    *,
    instance_id: str,
    status: str,
    error: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE connector_instance
            SET status = :status,
                last_error = :err,
                updated_at = now()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": instance_id, "status": status, "err": error},
    )


# ---------------------------------------------------------------------------
# Credential encryption (pgcrypto pgp_sym_*)
# ---------------------------------------------------------------------------


def _require_key() -> str:
    key = get_settings().connector_secret_key
    if not key:
        raise ConnectorError(
            "CONNECTOR_SECRET_KEY is not set; cannot store/load connector credentials"
        )
    return key


async def store_credentials(
    session: AsyncSession,
    *,
    instance_id: str,
    bundle: CredentialBundle,
) -> None:
    payload = json.dumps(bundle.data)
    await session.execute(
        text(
            """
            UPDATE connector_instance
            SET credentials_encrypted = pgp_sym_encrypt(:plain, :key),
                credentials_key_id = :kid,
                status = 'active',
                last_error = NULL,
                updated_at = now()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": instance_id,
            "plain": payload,
            "key": _require_key(),
            "kid": get_settings().connector_secret_key_id,
        },
    )


async def load_credentials(
    session: AsyncSession,
    *,
    instance_id: str,
) -> CredentialBundle | None:
    result = await session.execute(
        text(
            """
            SELECT pgp_sym_decrypt(credentials_encrypted, :key) AS plain
            FROM connector_instance
            WHERE id = CAST(:id AS uuid)
              AND credentials_encrypted IS NOT NULL
            """
        ),
        {"id": instance_id, "key": _require_key()},
    )
    row = result.first()
    if not row or not row[0]:
        return None
    return CredentialBundle(data=json.loads(row[0]))
