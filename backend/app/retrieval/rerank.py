"""Cross-encoder reranker for hybrid retrieval (RFC §18).

Disabled by default — flipped on per-deploy via ``RERANKER_ENABLED``.
When on, the top-N candidates from RRF go through a cross-encoder
scoring pass before MMR diversification.

We do NOT pull a heavyweight sentence-transformers / torch dependency at
import time. Instead, the model is loaded lazily on the first call, and
that call is wrapped in a thread executor so the asyncio loop stays
responsive. If the import or load fails (eg. CPU-only image, no
weights), we log + fall back to the original RRF order.

Tests inject a stub via ``set_score_fn`` to avoid any model loading.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Optional injection point for tests / alternate scorers.
# Signature: (query, passages) -> list[float] of length len(passages).
ScoreFn = Callable[[str, list[str]], Awaitable[list[float]] | list[float]]
_score_fn: ScoreFn | None = None


def set_score_fn(fn: ScoreFn | None) -> None:
    """Override the reranker's scoring function. Tests use this."""
    global _score_fn
    _score_fn = fn


async def rerank(
    query: str,
    items: list[dict[str, Any]],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return ``items`` re-ordered by cross-encoder score (desc).

    Each item must have a ``text`` field used as the passage. Items that
    score successfully get a new ``rerank_score`` key. The top
    ``top_n`` are reranked; the rest preserve their original order at
    the bottom of the result.
    """
    settings = get_settings()
    if not items:
        return items

    n = top_n or settings.reranker_top_n
    head = items[:n]
    tail = items[n:]

    passages = [str(it.get("text") or "") for it in head]
    try:
        scorer = _score_fn or _default_scorer
        scores = scorer(query, passages)
        if asyncio.iscoroutine(scores):
            scores = await scores  # type: ignore[assignment]
    except Exception as exc:
        log.warning("rerank.failed", error=str(exc))
        return items

    if not isinstance(scores, list) or len(scores) != len(head):
        log.warning(
            "rerank.bad_scores",
            received=type(scores).__name__,
            wanted=len(head),
        )
        return items

    for it, sc in zip(head, scores, strict=False):
        it["rerank_score"] = float(sc)

    head_sorted = sorted(head, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
    return head_sorted + tail


_model_cached: object | None = None


async def _default_scorer(query: str, passages: list[str]) -> list[float]:
    """Default cross-encoder using sentence-transformers via thread pool.

    The model is loaded lazily and cached for the process. Pure stub
    fallback when the dependency isn't installed in the running image.
    """
    global _model_cached
    if _model_cached is None:
        try:
            from sentence_transformers import CrossEncoder
            settings = get_settings()
            _model_cached = await asyncio.to_thread(
                CrossEncoder, settings.reranker_model
            )
        except Exception as exc:
            log.warning(
                "rerank.model_load_failed",
                error=str(exc),
                model=get_settings().reranker_model,
            )
            # Mark a sentinel so we don't keep retrying within the
            # process. Caller will see the fallback below on next call.
            _model_cached = _NULL_MODEL
            return [0.0] * len(passages)
    if _model_cached is _NULL_MODEL:
        return [0.0] * len(passages)

    pairs = [(query, p) for p in passages]
    model = _model_cached
    scores = await asyncio.to_thread(
        model.predict, pairs, show_progress_bar=False
    )
    return [float(s) for s in scores]


class _NullModel:
    """Sentinel for failed model load."""


_NULL_MODEL = _NullModel()
