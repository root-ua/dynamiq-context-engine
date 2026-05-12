"""LLM-driven contradiction judge for high-stakes edge writes.

Given a new fact + kNN of live edges with the same (subject, predicate),
asks the LLM whether the new fact contradicts, supports, or is unrelated
to each candidate. Closes the loser's ``valid_time`` at the new edge's
``valid_from`` timestamp.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.ontology import RelationType
from app.llm.provider import get_llm
from app.llm.vector_utils import to_pg_vector

log = get_logger(__name__)


class _Judgment(BaseModel):
    verdict: Literal["contradicts", "supports", "unrelated"] = Field(...)
    reasoning: str = Field(..., max_length=400)


SYSTEM_PROMPT = """You judge whether two facts describe the same world relationship and, if so, whether the new fact contradicts or supports the older one.

Return:
- "contradicts" if both facts claim the same subject-relation but the objects are different AND only one can be true at a time.
- "supports"    if they agree or the new fact is a more specific restatement.
- "unrelated"   if they describe different things (different subjects, different predicates, or compatible simultaneous facts like multi-value relations).

Be conservative: only say "contradicts" when you are confident the old fact must have become false."""


async def run(
    session: AsyncSession,
    *,
    workspace_id: str,
    subject_id: str,
    relation: RelationType,
    new_fact: str,
    new_fact_embedding: list[float] | None,
    new_valid_from: datetime,
    actor_id: str | None = None,
) -> int:
    """Close any live edge judged to be contradicted by the new fact.

    Returns the number of edges invalidated.
    """
    if not relation.high_stakes:
        return 0

    settings = get_settings()
    threshold = settings.contradictor_similarity_threshold

    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "subject_id": subject_id,
        "predicate_id": relation.id,
    }
    sql = _CANDIDATE_SELECT
    if new_fact_embedding:
        sql = _CANDIDATE_SELECT_WITH_EMBED
        params["embedding"] = to_pg_vector(new_fact_embedding)
        params["threshold"] = threshold

    result = await session.execute(text(sql), params)
    candidates = list(result.mappings())

    invalidated = 0
    if not candidates:
        return 0

    llm = get_llm()
    for cand in candidates:
        try:
            judgment = await llm.structured(
                schema=_Judgment,
                system=SYSTEM_PROMPT,
                user=(
                    f"Existing fact (valid from {cand['valid_from']}): "
                    f"\"{cand['fact']}\"\n"
                    f"New fact (valid from {new_valid_from.isoformat()}): "
                    f"\"{new_fact}\""
                ),
            )
        except Exception as exc:
            log.warning("contradictor.llm_failed", edge_id=cand["id"], error=str(exc))
            continue

        if judgment.verdict != "contradicts":
            continue

        await session.execute(
            text(
                """
                UPDATE edge
                SET sys_time = tstzrange(lower(sys_time), now(), '[)'),
                    valid_time = tstzrange(lower(valid_time), :vt_close, '[)')
                WHERE id = :id AND upper(sys_time) = 'infinity'
                """
            ),
            {"id": cand["id"], "vt_close": new_valid_from},
        )
        await session.execute(
            text(
                """
                INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                       target_kind, target_id, diff)
                VALUES (:workspace_id,
                        CASE WHEN :actor_id IS NULL THEN 'system' ELSE 'agent' END,
                        :actor_id,
                        'edge.invalidate.contradictor',
                        'edge', :id,
                        jsonb_build_object(
                          'reason', CAST(:reason AS text),
                          'new_fact', CAST(:new_fact AS text)))
                """
            ),
            {
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "id": cand["id"],
                "reason": judgment.reasoning,
                "new_fact": new_fact,
            },
        )
        invalidated += 1

    if invalidated:
        log.info("contradictor.invalidated", count=invalidated, subject_id=subject_id)
    return invalidated


_CANDIDATE_SELECT = """
SELECT id::text, fact, lower(valid_time)::text AS valid_from
FROM edge
WHERE workspace_id = :workspace_id
  AND subject_id = :subject_id
  AND predicate_id = :predicate_id
  AND upper(sys_time) = 'infinity'
ORDER BY lower(valid_time) DESC
LIMIT 5
"""

_CANDIDATE_SELECT_WITH_EMBED = """
SELECT id::text, fact, lower(valid_time)::text AS valid_from,
       1 - (fact_embedding <=> CAST(:embedding AS vector)) AS similarity
FROM edge
WHERE workspace_id = :workspace_id
  AND subject_id = :subject_id
  AND predicate_id = :predicate_id
  AND upper(sys_time) = 'infinity'
  AND fact_embedding IS NOT NULL
  AND (1 - (fact_embedding <=> CAST(:embedding AS vector))) >= :threshold
ORDER BY similarity DESC
LIMIT 5
"""
