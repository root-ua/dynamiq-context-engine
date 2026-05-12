"""Apply canned facts from a mock-mode crawled item.

Real connectors leave ``CrawledItem.canned_facts`` empty and let the LLM
extraction pipeline derive facts from ``content``. Mock connectors
populate it so the demo and pytest E2E run without API keys.

The flow is intentionally minimal: resolve each entity by canonical name
in the workspace (creating if absent), then call ``edge.add_fact`` with
``source_id`` pointing at the upserted episode. The same per-source ACL
filter applies on read because the edge inherits its provenance from
``source_id`` like any extracted edge would.

We pass ``embed=False`` to ``add_fact``: the embedding client requires
``OPENAI_API_KEY`` and we want this path to work without one. The
canned facts still show up in trigram + tsvector search because those
don't depend on embeddings.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import CannedFact
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import ontology as ontology_mod

log = logging.getLogger(__name__)


async def apply_canned_facts(
    session: AsyncSession,
    *,
    workspace_id: str,
    episode_id: str,
    facts: list[CannedFact],
    actor_id: str | None = None,
) -> int:
    """Insert each canned fact as an ``edge`` rooted at ``episode_id``.

    Returns the number of edges successfully inserted. Failures are
    logged and skipped — a single bad triple shouldn't abort the whole
    crawl.
    """
    inserted = 0
    for fact in facts:
        try:
            subject = await _resolve_or_create(
                session,
                workspace_id=workspace_id,
                canonical=fact.subject_canonical,
                type_slug=fact.subject_type_slug,
                actor_id=actor_id,
            )
            obj = await _resolve_or_create(
                session,
                workspace_id=workspace_id,
                canonical=fact.object_canonical,
                type_slug=fact.object_type_slug,
                actor_id=actor_id,
            )
            relation = await ontology_mod.get_relation_type(
                session, fact.predicate_slug
            )
            if relation is None:
                log.warning(
                    "canned.predicate_missing predicate=%s episode=%s",
                    fact.predicate_slug, episode_id,
                )
                continue
            await edge_mod.add_fact(
                session,
                workspace_id=workspace_id,
                subject_id=subject,
                predicate=relation.id,
                object_id=obj,
                fact=fact.fact_text,
                source_id=episode_id,
                source_kind="connector_mock",
                created_by=actor_id,
                embed=False,
                run_contradictor=False,
            )
            inserted += 1
        except Exception as exc:  # noqa: BLE001 — keep crawl moving on bad facts
            log.warning(
                "canned.fact_failed episode=%s err=%s fact=%r",
                episode_id, exc, fact.fact_text,
            )
    return inserted


async def _resolve_or_create(
    session: AsyncSession,
    *,
    workspace_id: str,
    canonical: str,
    type_slug: str,
    actor_id: str | None,
) -> str:
    """Find an entity by canonical name (or alias) within the workspace,
    or create one of the requested type.

    The match is case-insensitive on canonical via the existing
    ``resolve_by_alias`` similarity threshold; for canned facts we want
    high confidence, so we keep the threshold tight.
    """
    matches = await entity_mod.resolve_by_alias(
        session,
        workspace_id=workspace_id,
        name=canonical,
        type_ref=type_slug,
        similarity_threshold=0.9,
        limit=1,
    )
    if matches:
        return matches[0].id
    created = await entity_mod.create(
        session,
        workspace_id=workspace_id,
        type_ref=type_slug,
        canonical=canonical,
        aliases=[],
        summary=None,
        props={},
        created_by=actor_id,
        embed=False,
    )
    return created.id
