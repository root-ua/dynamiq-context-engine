"""Document + block tree service.

A document is an entity (of type "note" or "document") with a companion
row in ``document`` holding the Yjs binary state. The block tree is a
denormalized projection of the Yjs doc — the authoritative collaborative
state — into queryable rows. Projection is performed by Hocuspocus on
save and by this service on direct REST writes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import entity as entity_mod


class DocumentError(Exception):
    pass


@dataclass
class Document:
    id: str
    workspace_id: str
    entity_id: str
    title: str
    type_slug: str
    updated_at: str


@dataclass
class Block:
    id: str
    workspace_id: str
    document_id: str
    parent_block_id: str | None
    position: float
    block_type: str
    content: Any
    props: dict[str, Any]
    version: int
    search_text: str | None


async def create_document(
    session: AsyncSession,
    *,
    workspace_id: str,
    title: str,
    type_slug: str = "note",
    props: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> Document:
    """Create a new document-backed entity + its document row."""
    ent = await entity_mod.create(
        session,
        workspace_id=workspace_id,
        type_ref=type_slug,
        canonical=title,
        props=props or {},
        created_by=created_by,
        embed=False,
    )

    await session.execute(
        text(
            """
            INSERT INTO document (workspace_id, entity_id)
            VALUES (:workspace_id, :entity_id)
            """
        ),
        {"workspace_id": workspace_id, "entity_id": ent.id},
    )
    doc = await get_document_by_entity(session, ent.id)
    assert doc is not None
    return doc


async def get_document(session: AsyncSession, document_id: str) -> Document | None:
    result = await session.execute(
        text(
            """
            SELECT d.id::text AS id, d.workspace_id::text AS workspace_id,
                   d.entity_id::text AS entity_id,
                   e.canonical AS title, et.slug AS type_slug,
                   d.updated_at::text AS updated_at
            FROM document d
            JOIN entity e ON e.id = d.entity_id
            JOIN entity_type et ON et.id = e.type_id
            WHERE d.id = :id
            """
        ),
        {"id": document_id},
    )
    row = result.mappings().first()
    return _row_to_document(row) if row else None


async def get_document_by_entity(session: AsyncSession, entity_id: str) -> Document | None:
    result = await session.execute(
        text(
            """
            SELECT d.id::text AS id, d.workspace_id::text AS workspace_id,
                   d.entity_id::text AS entity_id,
                   e.canonical AS title, et.slug AS type_slug,
                   d.updated_at::text AS updated_at
            FROM document d
            JOIN entity e ON e.id = d.entity_id
            JOIN entity_type et ON et.id = e.type_id
            WHERE d.entity_id = :entity_id
            """
        ),
        {"entity_id": entity_id},
    )
    row = result.mappings().first()
    return _row_to_document(row) if row else None


async def list_documents(
    session: AsyncSession,
    *,
    workspace_id: str,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Document]:
    params: dict[str, Any] = {"workspace_id": workspace_id, "limit": limit, "offset": offset}
    where = ["d.workspace_id = :workspace_id"]
    if query:
        where.append("e.canonical ILIKE :q")
        params["q"] = f"%{query}%"
    sql = (
        "SELECT d.id::text AS id, d.workspace_id::text AS workspace_id,"
        "       d.entity_id::text AS entity_id,"
        "       e.canonical AS title, et.slug AS type_slug,"
        "       d.updated_at::text AS updated_at "
        "FROM document d "
        "JOIN entity e ON e.id = d.entity_id "
        "JOIN entity_type et ON et.id = e.type_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY d.updated_at DESC LIMIT :limit OFFSET :offset"
    )
    result = await session.execute(text(sql), params)
    return [_row_to_document(r) for r in result.mappings()]


async def delete_document(session: AsyncSession, document_id: str) -> None:
    # Document row is the SSoT of the Yjs state, but the entity is the
    # reference target. Soft-delete both.
    doc = await get_document(session, document_id)
    if not doc:
        return
    await entity_mod.soft_delete(session, doc.entity_id)
    await session.execute(
        text("DELETE FROM document WHERE id = :id"),
        {"id": document_id},
    )


# ---------------------------------------------------------------------------
# Block tree
# ---------------------------------------------------------------------------

async def replace_block_tree(
    session: AsyncSession,
    *,
    document_id: str,
    blocks: list[dict[str, Any]],
) -> None:
    """Replace the projected block tree for a document.

    `blocks` is a list of dicts with shape::

        {
          "id": "<uuid>",
          "parent_block_id": "<uuid?>",
          "position": <number>,
          "block_type": "paragraph",
          "content": <jsonb>,
          "props": <jsonb>,
          "search_text": "plain-text for FTS"
        }

    The update is idempotent and drives block_entity_ref rebuild.
    """
    doc = await get_document(session, document_id)
    if not doc:
        raise DocumentError("document not found")

    # Soft-delete blocks that disappear.
    ids = [b["id"] for b in blocks]
    await session.execute(
        text(
            """
            UPDATE block SET deleted_at = now()
            WHERE document_id = :doc_id
              AND deleted_at IS NULL
              AND id <> ALL(:ids)
            """
        ),
        {"doc_id": document_id, "ids": ids or ["00000000-0000-0000-0000-000000000000"]},
    )

    # Upsert each block.
    for block in blocks:
        await session.execute(
            text(
                """
                INSERT INTO block
                  (id, workspace_id, document_id, parent_block_id, position,
                   block_type, content, props, version, search_text, deleted_at)
                VALUES
                  (:id, :workspace_id, :document_id, :parent_id, :position,
                   :block_type, CAST(:content AS jsonb), CAST(:props AS jsonb),
                   1, :search_text, NULL)
                ON CONFLICT (id) DO UPDATE SET
                  parent_block_id = EXCLUDED.parent_block_id,
                  position = EXCLUDED.position,
                  block_type = EXCLUDED.block_type,
                  content = EXCLUDED.content,
                  props = EXCLUDED.props,
                  search_text = EXCLUDED.search_text,
                  version = block.version + 1,
                  deleted_at = NULL
                """
            ),
            {
                "id": block["id"],
                "workspace_id": doc.workspace_id,
                "document_id": document_id,
                "parent_id": block.get("parent_block_id"),
                "position": Decimal(str(block.get("position", 0))),
                "block_type": block.get("block_type", "paragraph"),
                "content": json.dumps(block.get("content", {})),
                "props": json.dumps(block.get("props", {})),
                "search_text": block.get("search_text"),
            },
        )

    # Rebuild block_entity_ref from the mentions embedded in content.
    await _rebuild_backlinks(session, document_id=document_id, blocks=blocks)


async def _rebuild_backlinks(
    session: AsyncSession,
    *,
    document_id: str,
    blocks: list[dict[str, Any]],
) -> None:
    # Delete existing refs for the document's blocks.
    await session.execute(
        text(
            """
            DELETE FROM block_entity_ref
            WHERE block_id IN (SELECT id FROM block WHERE document_id = :doc_id)
            """
        ),
        {"doc_id": document_id},
    )

    # Extract mention entityIds from each block's content.
    doc = await get_document(session, document_id)
    assert doc is not None
    inserts: list[dict[str, Any]] = []
    for block in blocks:
        for idx, mention in enumerate(_extract_mentions(block.get("content"))):
            inserts.append({
                "id": str(uuid4()),
                "workspace_id": doc.workspace_id,
                "block_id": block["id"],
                "entity_id": mention["entityId"],
                "mention_type": mention.get("mention_type", "mention"),
                "position": idx,
            })

    if not inserts:
        return

    for row in inserts:
        await session.execute(
            text(
                """
                INSERT INTO block_entity_ref
                  (id, workspace_id, block_id, entity_id, mention_type, position)
                VALUES
                  (:id, :workspace_id, :block_id, :entity_id, :mention_type, :position)
                ON CONFLICT (block_id, entity_id, position) DO NOTHING
                """
            ),
            row,
        )


def _extract_mentions(content: Any) -> list[dict[str, Any]]:
    """Walk BlockNote-style content tree, yielding entityMention inline nodes."""
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("type")
            props = node.get("props", {}) or {}
            if t == "entityMention" and "entityId" in props:
                out.append({
                    "entityId": props["entityId"],
                    "mention_type": props.get("mention_type", "mention"),
                })
            # Recurse children.
            for key in ("content", "children"):
                if isinstance(node.get(key), list):
                    for child in node[key]:
                        walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(content)
    return out


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def list_blocks(
    session: AsyncSession, *, document_id: str
) -> list[Block]:
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, document_id::text,
                   parent_block_id::text, position::float AS position,
                   block_type, content, props, version, search_text
            FROM block
            WHERE document_id = :doc_id AND deleted_at IS NULL
            ORDER BY position
            """
        ),
        {"doc_id": document_id},
    )
    return [
        Block(
            id=r["id"], workspace_id=r["workspace_id"], document_id=r["document_id"],
            parent_block_id=r["parent_block_id"], position=r["position"],
            block_type=r["block_type"], content=r["content"], props=r["props"] or {},
            version=r["version"], search_text=r["search_text"],
        )
        for r in result.mappings()
    ]


async def backlinks_for_entity(
    session: AsyncSession, *, entity_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT ref.block_id::text AS block_id,
                   b.document_id::text AS document_id,
                   e.canonical AS document_title,
                   b.block_type,
                   b.search_text
            FROM block_entity_ref ref
            JOIN block b ON b.id = ref.block_id
            JOIN document d ON d.id = b.document_id
            JOIN entity e ON e.id = d.entity_id
            WHERE ref.entity_id = :entity_id AND b.deleted_at IS NULL
            ORDER BY b.updated_at DESC
            LIMIT :limit
            """
        ),
        {"entity_id": entity_id, "limit": limit},
    )
    return [dict(r) for r in result.mappings()]


def _row_to_document(row: Any) -> Document:
    return Document(
        id=row["id"], workspace_id=row["workspace_id"], entity_id=row["entity_id"],
        title=row["title"], type_slug=row["type_slug"], updated_at=row["updated_at"],
    )
