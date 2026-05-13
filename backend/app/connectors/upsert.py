"""Framework helper: persist a CrawledItem as an episode + episode_acl.

This is the only place that should write connector-derived rows to the
database. It runs inside the worker's RLS-scoped session.

The flow:

1. Look up the episode by ``(workspace_id, connector_instance_id, external_id)``.
2. If no row exists, INSERT it. ``processing_status`` starts as
   ``pending``; the framework returns ``content_changed=True`` so the
   worker enqueues extraction.
3. If a row exists and the revision matches what we have on disk, only
   refresh the ACL projection. Skip re-extraction.
4. If the revision differs, UPDATE content + bump ``ingested_at`` and
   reset ``processing_status``. Re-extraction follows.
5. Replace ``episode_acl`` rows for the episode in the same transaction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ACLEntry, CrawledItem, DeletedItem


@dataclass
class UpsertResult:
    episode_id: str
    created: bool
    content_changed: bool
    acl_changed: bool


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def upsert_item(
    session: AsyncSession,
    *,
    workspace_id: str,
    connector_instance_id: str,
    item: CrawledItem,
) -> UpsertResult:
    new_hash = _content_hash(item.content)
    acl_payload = json.dumps([entry.model_dump() for entry in item.acl])

    existing = await session.execute(
        text(
            """
            SELECT id::text, external_revision_id, content_hash, acl::text
            FROM episode
            WHERE workspace_id = CAST(:ws AS uuid)
              AND connector_instance_id = CAST(:ci AS uuid)
              AND external_id = :ext
              AND deleted_at IS NULL
            """
        ),
        {"ws": workspace_id, "ci": connector_instance_id, "ext": item.external_id},
    )
    row = existing.mappings().first()

    if row is None:
        ins = await session.execute(
            text(
                """
                INSERT INTO episode (
                  workspace_id, source_kind, source_ref, occurred_at, content,
                  content_text, processing_status, connector_instance_id,
                  external_id, external_url, external_revision_id, content_hash,
                  mime_type, acl, acl_synced_at, last_modified_external
                ) VALUES (
                  CAST(:ws AS uuid), 'connector', :sref,
                  COALESCE(:occurred, now()),
                  CAST(:doc AS jsonb), :ctext, 'pending',
                  CAST(:ci AS uuid), :ext, :url, :rev, :hash, :mime,
                  CAST(:acl AS jsonb), now(), :modext
                )
                RETURNING id::text
                """
            ),
            {
                "ws": workspace_id,
                "ci": connector_instance_id,
                "sref": item.external_url,
                "occurred": item.last_modified_external,
                "doc": json.dumps({"title": item.title, "metadata": item.metadata}),
                "ctext": item.content,
                "ext": item.external_id,
                "url": item.external_url,
                "rev": item.external_revision_id,
                "hash": new_hash,
                "mime": item.mime_type,
                "acl": acl_payload,
                "modext": item.last_modified_external,
            },
        )
        new_id = ins.scalar_one()
        await _replace_acl(session, episode_id=new_id, workspace_id=workspace_id, acl=item.acl)
        return UpsertResult(episode_id=new_id, created=True, content_changed=True, acl_changed=True)

    episode_id = row["id"]
    existing_rev = row["external_revision_id"]
    existing_hash = row["content_hash"]
    revision_match = (
        item.external_revision_id is not None
        and existing_rev == item.external_revision_id
    )
    hash_match = existing_hash == new_hash
    content_changed = not (revision_match or hash_match)

    # Compare ACL JSON. The serialized form is canonical because ACLEntry
    # has a stable field order and we always serialize via model_dump.
    existing_acl_text = row.get("acl")
    acl_changed = existing_acl_text != acl_payload

    if content_changed:
        await session.execute(
            text(
                """
                UPDATE episode SET
                  content = CAST(:doc AS jsonb),
                  content_text = :ctext,
                  external_url = :url,
                  external_revision_id = :rev,
                  content_hash = :hash,
                  mime_type = :mime,
                  last_modified_external = :modext,
                  processing_status = 'pending',
                  processing_error = NULL,
                  acl = CAST(:acl AS jsonb),
                  acl_synced_at = now()
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": episode_id,
                "doc": json.dumps({"title": item.title, "metadata": item.metadata}),
                "ctext": item.content,
                "url": item.external_url,
                "rev": item.external_revision_id,
                "hash": new_hash,
                "mime": item.mime_type,
                "modext": item.last_modified_external,
                "acl": acl_payload,
            },
        )
    elif acl_changed:
        await session.execute(
            text(
                """
                UPDATE episode SET acl = CAST(:acl AS jsonb), acl_synced_at = now()
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": episode_id, "acl": acl_payload},
        )

    if acl_changed or content_changed:
        await _replace_acl(session, episode_id=episode_id, workspace_id=workspace_id, acl=item.acl)

    return UpsertResult(
        episode_id=episode_id,
        created=False,
        content_changed=content_changed,
        acl_changed=acl_changed,
    )


async def soft_delete_item(
    session: AsyncSession,
    *,
    workspace_id: str,
    connector_instance_id: str,
    item: DeletedItem,
) -> str | None:
    """Mark a previously-ingested episode as deleted.

    Returns the episode id if a row was found, else None.
    Edges remain (bi-temporal: invalidate, never delete) but become
    invisible because the source episode is now soft-deleted and the
    visibility filter excludes ``episode.deleted_at IS NOT NULL``.
    """
    result = await session.execute(
        text(
            """
            UPDATE episode SET deleted_at = now()
            WHERE workspace_id = CAST(:ws AS uuid)
              AND connector_instance_id = CAST(:ci AS uuid)
              AND external_id = :ext
              AND deleted_at IS NULL
            RETURNING id::text
            """
        ),
        {"ws": workspace_id, "ci": connector_instance_id, "ext": item.external_id},
    )
    row = result.first()
    return row[0] if row else None


async def _replace_acl(
    session: AsyncSession,
    *,
    episode_id: str,
    workspace_id: str,
    acl: list[ACLEntry],
) -> None:
    """Atomically replace the episode_acl rows for one episode."""
    await session.execute(
        text("DELETE FROM episode_acl WHERE episode_id = CAST(:id AS uuid)"),
        {"id": episode_id},
    )
    if not acl:
        return
    # Bulk insert via VALUES list. Pydantic guarantees the kind enum.
    rows = [
        {
            "ws": workspace_id,
            "ep": episode_id,
            "kind": entry.kind,
            "ext": entry.external_id,
            "role": entry.role,
        }
        for entry in acl
    ]
    await session.execute(
        text(
            """
            INSERT INTO episode_acl
              (episode_id, workspace_id, principal_kind, principal_external_id, role)
            VALUES (CAST(:ep AS uuid), CAST(:ws AS uuid), :kind, :ext, :role)
            ON CONFLICT (episode_id, principal_kind, principal_external_id) DO NOTHING
            """
        ),
        rows,
    )
