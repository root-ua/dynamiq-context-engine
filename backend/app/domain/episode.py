"""Episode service — non-lossy ingestion of raw content."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embedding import get_embedding_client
from app.llm.vector_utils import to_pg_vector


@dataclass
class Episode:
    id: str
    workspace_id: str
    source_kind: str
    source_ref: str | None
    occurred_at: str
    ingested_at: str
    content: Any
    content_text: str | None
    processing_status: str
    processing_error: str | None


async def add_episode(
    session: AsyncSession,
    *,
    workspace_id: str,
    content: str | dict[str, Any],
    source_kind: str,
    source_ref: str | None = None,
    occurred_at: datetime | None = None,
    created_by: str | None = None,
    embed: bool = True,
) -> Episode:
    content_text, content_json = _normalize_content(content)
    occurred = occurred_at or datetime.now(UTC)

    embedding = None
    if embed and content_text:
        try:
            embedding = await get_embedding_client().embed_one(content_text)
        except Exception:
            embedding = None

    episode_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO episode
              (id, workspace_id, source_kind, source_ref, occurred_at,
               content, content_text, content_embedding, processing_status, created_by)
            VALUES
              (:id, :workspace_id, :source_kind, :source_ref, :occurred_at,
               CAST(:content AS jsonb), :content_text,
               CAST(:embedding AS vector), 'pending', :created_by)
            """
        ),
        {
            "id": episode_id,
            "workspace_id": workspace_id,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "occurred_at": occurred,
            "content": json.dumps(content_json),
            "content_text": content_text,
            "embedding": to_pg_vector(embedding),
            "created_by": created_by,
        },
    )
    fetched = await get(session, episode_id)
    assert fetched is not None
    return fetched


async def get(session: AsyncSession, episode_id: str) -> Episode | None:
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, source_kind, source_ref,
                   occurred_at::text, ingested_at::text, content, content_text,
                   processing_status, processing_error
            FROM episode WHERE id = :id
            """
        ),
        {"id": episode_id},
    )
    row = result.mappings().first()
    return Episode(**dict(row)) if row else None


async def list_episodes(
    session: AsyncSession,
    *,
    workspace_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Episode]:
    params: dict[str, Any] = {"workspace_id": workspace_id, "limit": limit, "offset": offset}
    where = ["workspace_id = :workspace_id"]
    if status:
        where.append("processing_status = :status")
        params["status"] = status

    result = await session.execute(
        text(
            f"""
            SELECT id::text, workspace_id::text, source_kind, source_ref,
                   occurred_at::text, ingested_at::text, content, content_text,
                   processing_status, processing_error
            FROM episode
            WHERE {' AND '.join(where)}
            ORDER BY occurred_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    return [Episode(**dict(r)) for r in result.mappings()]


def _normalize_content(content: str | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(content, str):
        return content, {"text": content}
    text_val = content.get("text") or _collect_text(content) or ""
    return text_val, content


def _collect_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(_collect_text(v) for v in obj.values() if v)
    if isinstance(obj, list):
        return "\n".join(_collect_text(v) for v in obj)
    return ""
