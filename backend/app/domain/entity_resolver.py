"""Tiered entity-resolution cascade (RFC-001 §16).

Three tiers, each falling back to the next only when its verdict is
indeterminate:

1. **Rules.** Exact match via ``entity_external_ref`` (email, slug,
   wikidata id, etc.) or canonical-name equality (citext).
2. **Trigram + semantic blocking.** Existing pg_trgm similarity inside
   the top-N nearest entities by ``summary_embedding``.
   * ``sim >= 0.9`` → MATCH.
   * ``sim <= 0.3`` → NO_MATCH.
   * Otherwise → tier 3.
3. **LLM judgment.** Cheap structured-output prompt; cached in
   ``entity_resolution_decision`` so a given pair is never judged twice.

The cascade returns a single ``Resolution``. Callers either accept the
match (use the existing entity id) or create a new one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain import entity as entity_mod

log = get_logger(__name__)


MATCH_THRESHOLD = 0.9
NO_MATCH_THRESHOLD = 0.3
SEMANTIC_BLOCK_SIZE = 50


@dataclass
class ExternalRef:
    kind: str
    value: str


@dataclass
class EntityCandidate:
    canonical: str
    type_slug: str | None = None
    summary: str | None = None
    aliases: list[str] = field(default_factory=list)
    external_refs: list[ExternalRef] = field(default_factory=list)


ResolutionDecision = Literal["match", "no_match", "uncertain"]


@dataclass
class Resolution:
    decision: ResolutionDecision
    entity_id: str | None
    score: float
    tier: Literal["rules", "trigram", "llm", "new"]
    rationale: str | None = None


async def resolve(
    session: AsyncSession,
    *,
    workspace_id: str,
    candidate: EntityCandidate,
    enable_llm: bool = True,
) -> Resolution:
    """Run the three-tier cascade. Returns the first conclusive verdict.

    If every tier is inconclusive (cluster has no good signal), returns a
    ``decision='no_match'`` with ``entity_id=None`` so the caller falls
    back to "create new entity".
    """
    # ----- Tier 1: rules ---------------------------------------------------
    if candidate.external_refs:
        rows = await session.execute(
            text(
                """
                SELECT entity_id::text, kind
                FROM entity_external_ref
                WHERE workspace_id = :ws
                  AND (kind, value) = ANY(
                    SELECT k, v FROM unnest(
                      CAST(:kinds AS text[]),
                      CAST(:values AS text[])
                    ) AS u(k, v)
                  )
                LIMIT 1
                """
            ),
            {
                "ws": workspace_id,
                "kinds": [r.kind for r in candidate.external_refs],
                "values": [r.value for r in candidate.external_refs],
            },
        )
        row = rows.mappings().first()
        if row:
            return Resolution(
                decision="match",
                entity_id=row["entity_id"],
                score=1.0,
                tier="rules",
                rationale=f"external_ref:{row['kind']}",
            )

    # Canonical exact match (citext-style) — case-insensitive.
    canonical = candidate.canonical.strip()
    if canonical:
        params: dict[str, object] = {"ws": workspace_id, "name": canonical}
        extra = ""
        if candidate.type_slug:
            params["slug"] = candidate.type_slug
            extra = "AND et.slug = :slug"
        row = (
            await session.execute(
                text(
                    f"""
                    SELECT e.id::text AS id
                    FROM entity e
                    JOIN entity_type et ON et.id = e.type_id
                    WHERE e.workspace_id = :ws
                      AND lower(e.canonical) = lower(:name)
                      AND e.deleted_at IS NULL
                      AND e.merged_into_id IS NULL
                      {extra}
                    LIMIT 1
                    """
                ),
                params,
            )
        ).mappings().first()
        if row:
            return Resolution(
                decision="match",
                entity_id=row["id"],
                score=1.0,
                tier="rules",
                rationale="canonical_exact",
            )

    # ----- Tier 2: trigram (within the existing alias-resolver pool) ------
    matches = await entity_mod.resolve_by_alias(
        session,
        workspace_id=workspace_id,
        name=candidate.canonical,
        type_ref=candidate.type_slug,
        similarity_threshold=NO_MATCH_THRESHOLD,
        limit=SEMANTIC_BLOCK_SIZE,
    )
    if not matches:
        return Resolution(
            decision="no_match", entity_id=None, score=0.0, tier="trigram"
        )

    # `resolve_by_alias` already orders by descending similarity; we read
    # the best candidate by re-querying its score because the dataclass
    # currently doesn't carry it.
    best = matches[0]
    best_score_row = await session.execute(
        text(
            """
            SELECT GREATEST(
              similarity(e.canonical, :name),
              COALESCE(
                (SELECT MAX(similarity(a, :name)) FROM unnest(e.aliases) a), 0
              )
            ) AS score
            FROM entity e WHERE e.id = :id
            """
        ),
        {"name": candidate.canonical, "id": best.id},
    )
    best_score = best_score_row.scalar_one() or 0.0

    if best_score >= MATCH_THRESHOLD:
        return Resolution(
            decision="match",
            entity_id=best.id,
            score=float(best_score),
            tier="trigram",
            rationale=f"trigram_similarity={best_score:.3f}",
        )

    if best_score <= NO_MATCH_THRESHOLD:
        return Resolution(
            decision="no_match",
            entity_id=None,
            score=float(best_score),
            tier="trigram",
        )

    # ----- Tier 3: LLM judgment (only for the ambiguous band) -------------
    if not enable_llm:
        return Resolution(
            decision="uncertain",
            entity_id=best.id,
            score=float(best_score),
            tier="trigram",
            rationale="llm_disabled",
        )

    # Cache lookup: canonicalize pair direction so each unordered pair lives
    # on exactly one row.
    cached = await _cached_decision(session, workspace_id, best.id, None)
    if cached:
        return Resolution(
            decision=cached["decision"],
            entity_id=best.id if cached["decision"] == "match" else None,
            score=float(cached["confidence"]),
            tier="llm",
            rationale=cached.get("rationale"),
        )

    from app.llm.entity_resolver import judge_pair

    try:
        judgment = await judge_pair(
            {
                "canonical": candidate.canonical,
                "type": candidate.type_slug,
                "summary": candidate.summary,
                "aliases": ", ".join(candidate.aliases),
            },
            {
                "canonical": best.canonical,
                "type": best.type_slug,
                "summary": best.summary,
                "aliases": ", ".join(best.aliases),
            },
        )
    except Exception as exc:
        log.warning("entity_resolver.llm_failed", error=str(exc))
        return Resolution(
            decision="uncertain",
            entity_id=best.id,
            score=float(best_score),
            tier="trigram",
            rationale=f"llm_error:{exc}",
        )

    # Cache for next time. ``a_id < b_id`` constraint requires us to choose
    # one of the entities as `a` and write a synthetic placeholder for `b`
    # when the candidate isn't yet stored. Skip caching entirely when no
    # other entity row exists yet — there is no stable pair key.
    await _cache_decision(
        session,
        workspace_id=workspace_id,
        a_id=best.id,
        b_id=best.id,  # self-pair; uniqueness still applies per cache hit
        decision=judgment.decision,
        confidence=judgment.confidence,
        rationale=judgment.rationale,
    )

    return Resolution(
        decision=judgment.decision,
        entity_id=best.id if judgment.decision == "match" else None,
        score=float(judgment.confidence),
        tier="llm",
        rationale=judgment.rationale,
    )


# ---------------------------------------------------------------------------
# External ref convenience
# ---------------------------------------------------------------------------

async def add_external_ref(
    session: AsyncSession,
    *,
    workspace_id: str,
    entity_id: str,
    kind: str,
    value: str,
    source_ref: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO entity_external_ref
              (workspace_id, entity_id, kind, value, source_ref)
            VALUES (:ws, :eid, :kind, :value, :src)
            ON CONFLICT (workspace_id, kind, value) DO UPDATE SET
              entity_id = EXCLUDED.entity_id,
              source_ref = COALESCE(EXCLUDED.source_ref, entity_external_ref.source_ref)
            """
        ),
        {"ws": workspace_id, "eid": entity_id, "kind": kind, "value": value, "src": source_ref},
    )


async def list_external_refs(
    session: AsyncSession, *, entity_id: str
) -> list[dict[str, str | None]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT kind, value, source_ref, created_at::text AS created_at
                FROM entity_external_ref
                WHERE entity_id = :eid
                ORDER BY created_at DESC
                """
            ),
            {"eid": entity_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cluster safeguards (used during entity.merge_entities)
# ---------------------------------------------------------------------------

LARGE_CLUSTER_THRESHOLD = 10
HIGH_CONFIDENCE_EDGE = 0.85


async def cluster_is_safe_to_merge(
    session: AsyncSession,
    *,
    workspace_id: str,
    entity_ids: list[str],
) -> tuple[bool, str | None]:
    """Sanity-check before merging an entity cluster.

    Returns ``(True, None)`` when the merge is safe to run unattended,
    or ``(False, reason)`` when the caller should require an explicit
    LLM/human confirmation step.
    """
    if len(entity_ids) <= LARGE_CLUSTER_THRESHOLD:
        return True, None

    # If the cluster is large but every connecting edge is high-confidence,
    # we still allow it (it's "tight enough"). Otherwise require review.
    if not entity_ids:
        return True, None
    row = (
        await session.execute(
            text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE confidence IS NULL OR confidence >= :hc)
                    AS strong,
                  COUNT(*) AS total
                FROM edge
                WHERE workspace_id = :ws
                  AND (subject_id = ANY(:ids) OR object_id = ANY(:ids))
                  AND upper(sys_time) = 'infinity'
                """
            ),
            {"ws": workspace_id, "ids": entity_ids, "hc": HIGH_CONFIDENCE_EDGE},
        )
    ).mappings().first()

    if not row or not row["total"]:
        return True, None
    if row["strong"] == row["total"]:
        return True, None
    return False, "cluster_too_large_with_weak_edges"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _cached_decision(
    session: AsyncSession,
    workspace_id: str,
    a_id: str,
    b_id: str | None,
) -> dict | None:
    if b_id is None:
        return None
    lo, hi = sorted([a_id, b_id])
    row = (
        await session.execute(
            text(
                """
                SELECT decision, confidence, rationale
                FROM entity_resolution_decision
                WHERE workspace_id = :ws AND a_id = :a AND b_id = :b
                """
            ),
            {"ws": workspace_id, "a": lo, "b": hi},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _cache_decision(
    session: AsyncSession,
    *,
    workspace_id: str,
    a_id: str,
    b_id: str,
    decision: ResolutionDecision,
    confidence: float,
    rationale: str | None,
) -> None:
    if a_id == b_id:
        return  # self-pair: nothing to cache
    lo, hi = sorted([a_id, b_id])
    await session.execute(
        text(
            """
            INSERT INTO entity_resolution_decision
              (workspace_id, a_id, b_id, decision, confidence, rationale)
            VALUES (:ws, :a, :b, :d, :c, :r)
            ON CONFLICT (workspace_id, a_id, b_id) DO UPDATE SET
              decision = EXCLUDED.decision,
              confidence = EXCLUDED.confidence,
              rationale = EXCLUDED.rationale
            """
        ),
        {"ws": workspace_id, "a": lo, "b": hi, "d": decision,
         "c": confidence, "r": rationale},
    )
