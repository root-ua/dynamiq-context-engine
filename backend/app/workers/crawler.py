"""Connector crawler Arq jobs.

Three jobs:

* ``crawl_initial(connector_instance_id)`` — full inventory pass for a
  newly-installed connector. Self-schedules an incremental on completion.
* ``crawl_incremental(connector_instance_id)`` — change-feed pass.
  Self-reschedules every 15 minutes until the connector is paused or
  soft-deleted.
* ``refresh_acl(episode_id)`` — single-episode ACL re-fetch. Used by the
  "Resync ACLs" UI button.

The crawler is the only writer of connector-derived episodes. It opens
an RLS-scoped session per workspace and routes each yielded
``CrawledItem`` / ``DeletedItem`` through ``app.connectors.upsert`` so
the canonical ACL snapshot and the indexed ``episode_acl`` projection
stay consistent.

Crawls write audit-log rows so workspace owners can see who installed
what and when each pass ran.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.connectors import registry
from app.connectors.base import CrawledItem, DeletedItem
from app.connectors.canned import apply_canned_facts
from app.connectors.upsert import (
    UpsertResult,
    soft_delete_item,
    upsert_item,
    _replace_acl,
)
from app.db.session import session_scope
from app.domain import connector as connector_domain
from app.workers.queue import enqueue_extraction

log = logging.getLogger(__name__)


_INCREMENTAL_INTERVAL_SECONDS = 15 * 60


# ---------------------------------------------------------------------------
# Job: initial crawl
# ---------------------------------------------------------------------------


async def crawl_initial(ctx: dict, *, connector_instance_id: str) -> dict[str, Any]:
    return await _run_crawl(
        ctx,
        connector_instance_id=connector_instance_id,
        incremental=False,
    )


async def crawl_incremental(
    ctx: dict, *, connector_instance_id: str
) -> dict[str, Any]:
    return await _run_crawl(
        ctx,
        connector_instance_id=connector_instance_id,
        incremental=True,
    )


# ---------------------------------------------------------------------------
# Shared crawl driver
# ---------------------------------------------------------------------------


async def _run_crawl(
    ctx: dict,
    *,
    connector_instance_id: str,
    incremental: bool,
) -> dict[str, Any]:
    """Drive one crawl pass. Returns counts; persists state.

    Steps:
    1. Load instance row + decrypt credentials.
    2. Refuse if status is not crawlable (deleted / paused / inactive).
    3. Iterate the connector's stream of items. For each:
       - Upsert via ``upsert_item`` (or soft-delete).
       - If content changed, enqueue extraction.
    4. Persist final cursor + last_*_crawl_at.
    5. Write audit log.
    6. If this was an initial crawl, kick off the first incremental.
       If it was incremental and the connector is still active, schedule
       the next one.
    """
    counts = {"created": 0, "updated": 0, "deleted": 0, "errors": 0, "extracted": 0}

    # Step 1: load instance + credentials. Use a workspace-less session
    # because we don't yet know which workspace this row belongs to.
    async with session_scope() as session:
        instance = await connector_domain.get(session, instance_id=connector_instance_id)
        if instance is None:
            log.warning("crawler.instance_missing id=%s", connector_instance_id)
            return counts
        if instance.deleted_at is not None:
            log.info("crawler.instance_soft_deleted id=%s", connector_instance_id)
            return counts
        if instance.status in ("paused", "inactive"):
            log.info(
                "crawler.instance_not_crawlable id=%s status=%s",
                connector_instance_id, instance.status,
            )
            return counts
        credentials = await connector_domain.load_credentials(
            session, instance_id=connector_instance_id
        )
        if credentials is None:
            log.warning(
                "crawler.no_credentials id=%s — connector may have been revoked",
                connector_instance_id,
            )
            await connector_domain.mark_status(
                session, instance_id=connector_instance_id,
                status="error", error="credentials missing",
            )
            return counts

    # Step 2: lookup connector class.
    try:
        registry._import_connectors()  # ensure registration ran
        cls = registry.get(instance.connector_kind)
    except KeyError:
        log.error("crawler.unknown_kind kind=%s", instance.connector_kind)
        async with session_scope() as session:
            await connector_domain.mark_status(
                session, instance_id=connector_instance_id,
                status="error", error=f"unknown connector kind: {instance.connector_kind}",
            )
        return counts
    connector = cls()

    # Step 3: iterate items inside an RLS-scoped session for the
    # workspace this connector belongs to.
    cursor = dict(instance.cursor or {})
    workspace_id = instance.workspace_id

    async with session_scope(workspace_id=workspace_id) as session:
        crawl_iter = (
            connector.incremental_crawl(
                instance_id=connector_instance_id,
                config=instance.config,
                credentials=credentials,
                cursor=cursor,
            )
            if incremental
            else connector.initial_crawl(
                instance_id=connector_instance_id,
                config=instance.config,
                credentials=credentials,
                cursor=cursor,
            )
        )

        try:
            async for yielded in crawl_iter:
                if isinstance(yielded, DeletedItem):
                    deleted_id = await soft_delete_item(
                        session,
                        workspace_id=workspace_id,
                        connector_instance_id=connector_instance_id,
                        item=yielded,
                    )
                    if deleted_id:
                        counts["deleted"] += 1
                    continue

                assert isinstance(yielded, CrawledItem)
                try:
                    result: UpsertResult = await upsert_item(
                        session,
                        workspace_id=workspace_id,
                        connector_instance_id=connector_instance_id,
                        item=yielded,
                    )
                except Exception as exc:  # noqa: BLE001 — log and continue
                    counts["errors"] += 1
                    log.warning(
                        "crawler.upsert_failed external_id=%s err=%s",
                        yielded.external_id, exc,
                    )
                    continue

                if result.created:
                    counts["created"] += 1
                elif result.content_changed or result.acl_changed:
                    counts["updated"] += 1

                if result.content_changed:
                    # Mock-mode connectors carry pre-decided facts so the
                    # demo can exercise the ACL filter without an LLM
                    # API key. Real-mode connectors leave canned_facts
                    # empty and we enqueue the LLM extraction pipeline
                    # instead, which writes edges asynchronously.
                    if yielded.canned_facts:
                        n = await apply_canned_facts(
                            session,
                            workspace_id=workspace_id,
                            episode_id=result.episode_id,
                            facts=yielded.canned_facts,
                            actor_id=instance.created_by,
                        )
                        counts["extracted"] += n
                        # Mark the episode completed since we just ran
                        # the equivalent of extraction inline.
                        await session.execute(
                            text(
                                "UPDATE episode SET processing_status = 'completed' "
                                "WHERE id = CAST(:id AS uuid)"
                            ),
                            {"id": result.episode_id},
                        )
                        continue
                    # Extraction runs in a different worker job; the
                    # service-token user is the actor for audit purposes.
                    await enqueue_extraction(
                        workspace_id=workspace_id,
                        episode_id=result.episode_id,
                        actor_id=instance.created_by,
                    )
                    counts["extracted"] += 1
        except Exception as exc:  # noqa: BLE001 — top-level crawl error
            log.exception("crawler.fatal id=%s", connector_instance_id)
            await connector_domain.mark_status(
                session, instance_id=connector_instance_id,
                status="error", error=str(exc),
            )
            return counts

        # Step 4: persist cursor + timestamp. Tick the mock counter so
        # subsequent incremental calls yield different items.
        if incremental:
            cursor["mock_tick"] = int(cursor.get("mock_tick", 0)) + 1
        await connector_domain.update_cursor(
            session,
            instance_id=connector_instance_id,
            cursor=cursor,
            incremental=incremental,
        )
        await connector_domain.mark_status(
            session, instance_id=connector_instance_id, status="active"
        )

        # Step 5: audit log.
        action = (
            "connector.incremental_crawl.completed"
            if incremental
            else "connector.initial_crawl.completed"
        )
        await session.execute(
            text(
                """
                INSERT INTO audit_log
                  (workspace_id, actor_kind, actor_id, action,
                   target_kind, target_id, diff)
                VALUES (
                  CAST(:ws AS uuid), 'system', NULL, :action,
                  'connector_instance', CAST(:id AS uuid), CAST(:diff AS jsonb)
                )
                """
            ),
            {
                "ws": workspace_id,
                "action": action,
                "id": connector_instance_id,
                "diff": json.dumps(counts),
            },
        )

    # Step 6: schedule the next pass.
    if not incremental:
        # First incremental immediately on completion of initial crawl.
        await _enqueue_self(
            ctx,
            "crawl_incremental",
            connector_instance_id=connector_instance_id,
            defer_seconds=_INCREMENTAL_INTERVAL_SECONDS,
        )
    else:
        await _enqueue_self(
            ctx,
            "crawl_incremental",
            connector_instance_id=connector_instance_id,
            defer_seconds=_INCREMENTAL_INTERVAL_SECONDS,
        )

    return counts


# ---------------------------------------------------------------------------
# Targeted ACL refresh
# ---------------------------------------------------------------------------


async def refresh_acl(ctx: dict, *, episode_id: str) -> dict[str, Any]:
    """Re-fetch one episode's ACL from its source connector.

    Triggered by the "Resync ACLs" UI button. Atomically replaces the
    ``episode_acl`` rows.
    """
    async with session_scope() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT episode.id::text AS id, episode.workspace_id::text AS ws,
                           episode.external_id, episode.connector_instance_id::text AS ci
                    FROM episode
                    WHERE episode.id = CAST(:id AS uuid)
                      AND episode.connector_instance_id IS NOT NULL
                      AND episode.deleted_at IS NULL
                    """
                ),
                {"id": episode_id},
            )
        ).mappings().first()
        if row is None:
            return {"refreshed": 0}

    async with session_scope(workspace_id=row["ws"]) as session:
        instance = await connector_domain.get(session, instance_id=row["ci"])
        if instance is None:
            return {"refreshed": 0}
        credentials = await connector_domain.load_credentials(
            session, instance_id=row["ci"]
        )
        if credentials is None:
            return {"refreshed": 0}

        registry._import_connectors()
        connector = registry.get(instance.connector_kind)()
        try:
            new_acl = await connector.fetch_acl(
                external_id=row["external_id"],
                config=instance.config,
                credentials=credentials,
            )
        except NotImplementedError:
            log.info(
                "crawler.refresh_acl_unsupported kind=%s — falling back to incremental crawl",
                instance.connector_kind,
            )
            return {"refreshed": 0}

        await _replace_acl(
            session,
            episode_id=episode_id,
            workspace_id=row["ws"],
            acl=new_acl,
        )
        await session.execute(
            text(
                """
                UPDATE episode SET acl_synced_at = now()
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": episode_id},
        )
    return {"refreshed": 1, "acl_entries": len(new_acl)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _enqueue_self(
    ctx: dict,
    job_name: str,
    *,
    connector_instance_id: str,
    defer_seconds: int,
) -> None:
    """Enqueue another crawler job. Uses the queue from the existing Arq
    pool; falls back to the request-time pool helper if ctx['redis'] is
    missing (e.g. in tests).
    """
    redis = ctx.get("redis") if isinstance(ctx, dict) else None
    if redis is None:
        from app.workers.queue import get_queue

        redis = await get_queue()
    await redis.enqueue_job(
        job_name,
        connector_instance_id=connector_instance_id,
        _defer_by=defer_seconds,
    )
