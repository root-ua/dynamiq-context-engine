"""Small LLM judge for ambiguous entity pairs.

Used by the tier-3 step of the entity-resolution cascade. The prompt is
intentionally tiny (under ~250 tokens of context) so this stays cheap to
fire on the uncertain band.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.llm.provider import LLMClient


class EntityJudgment(BaseModel):
    decision: Literal["match", "no_match", "uncertain"] = Field(
        ..., description="Whether the two entities denote the same real-world thing."
    )
    confidence: float = Field(..., ge=0, le=1)
    rationale: str = Field(..., max_length=600)


SYSTEM_PROMPT = """You decide whether two short entity descriptions refer to the same real-world thing (same person, same organization, same project, etc.).

Output exactly one decision:
- "match" — same thing, with at least 0.7 confidence.
- "no_match" — different things, with at least 0.7 confidence.
- "uncertain" — under 0.7 confidence either way.

Be conservative: if the canonical names look similar but the contexts disagree (different roles, different employers, different time-spans), prefer "no_match" or "uncertain".

Keep the rationale to one short sentence (under 30 words)."""


async def judge_pair(
    a: dict[str, str | None],
    b: dict[str, str | None],
    *,
    model_override: str | None = None,
) -> EntityJudgment:
    """Compare two entity dicts of shape {canonical, type, summary, aliases}.

    Defaults to ``ENTITY_RESOLVER_LLM_MODEL`` (typically ``claude-haiku-4-5``)
    so each judgment is cheap.
    """
    settings = get_settings()
    model = model_override or getattr(
        settings, "entity_resolver_llm_model", None
    ) or settings.llm_model

    client = LLMClient(model=model)

    def _summarize(e: dict[str, str | None]) -> str:
        parts = [f"canonical: {e.get('canonical') or '?'}"]
        if e.get("type"):
            parts.append(f"type: {e['type']}")
        if e.get("aliases"):
            parts.append(f"aliases: {e['aliases']}")
        if e.get("summary"):
            parts.append(f"summary: {e['summary']}")
        return "\n".join(parts)

    user = (
        "Entity A:\n"
        f"{_summarize(a)}\n\n"
        "Entity B:\n"
        f"{_summarize(b)}\n\n"
        "Do A and B refer to the same real-world thing?"
    )

    return await client.structured(
        schema=EntityJudgment,
        system=SYSTEM_PROMPT,
        user=user,
        temperature=0.0,
        max_tokens=400,
    )
