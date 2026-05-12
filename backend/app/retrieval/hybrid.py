"""Hybrid retrieval: vector + tsvector + trigram, fused with RRF + MMR.

Returns a list of ``SearchResult`` ranked by fused relevance. Results
span entities, edges, episodes, and blocks — typed via the ``kind``
field so the caller (REST / MCP) can render or embed them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.acl import edge_visibility_clause, episode_visibility_clause
from app.auth.jwt import Principal
from app.core.config import get_settings
from app.llm.embedding import get_embedding_client
from app.llm.vector_utils import to_pg_vector


@dataclass
class SearchResult:
    kind: str  # "entity" | "edge" | "episode" | "block"
    id: str
    title: str
    snippet: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.kind}:{self.id}"


async def search(
    session: AsyncSession,
    *,
    workspace_id: str,
    query: str,
    limit: int = 20,
    include_kinds: tuple[str, ...] = ("entity", "edge", "episode", "block"),
    entity_type: str | None = None,
    as_of_valid: str | None = None,
    graph_expand: bool = False,
    principal: Principal | None = None,
) -> list[SearchResult]:
    settings = get_settings()
    if not query.strip():
        return []

    try:
        embedding = await get_embedding_client().embed_one(query)
    except Exception:
        embedding = None

    candidates: list[list[SearchResult]] = []

    if "entity" in include_kinds:
        candidates.append(await _entity_vector(session, workspace_id, embedding, entity_type))
        candidates.append(await _entity_text(session, workspace_id, query, entity_type))
    if "edge" in include_kinds:
        candidates.append(await _edge_vector(session, workspace_id, embedding, as_of_valid, principal=principal))
        candidates.append(await _edge_text(session, workspace_id, query, as_of_valid, principal=principal))
    if "episode" in include_kinds:
        candidates.append(await _episode_vector(session, workspace_id, embedding, principal=principal))
        candidates.append(await _episode_text(session, workspace_id, query, principal=principal))
    if "block" in include_kinds:
        candidates.append(await _block_text(session, workspace_id, query))

    fused = _rrf(candidates, k=settings.hybrid_rrf_k)
    if graph_expand and fused:
        fused = await _graph_expand(session, workspace_id, fused, limit=limit * 2, principal=principal)

    # MMR for diversity.
    reranked = _mmr(fused, k=limit, lambda_=0.7)
    return reranked[:limit]


# ---------------------------------------------------------------------------
# Candidate generators
# ---------------------------------------------------------------------------

async def _entity_vector(
    session: AsyncSession, workspace_id: str, embedding: list[float] | None,
    entity_type: str | None,
) -> list[SearchResult]:
    if embedding is None:
        return []
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "embedding": to_pg_vector(embedding),
        "limit": 50,
    }
    extra = ""
    if entity_type:
        extra = """
            AND e.type_id IN (
              SELECT et.id FROM entity_type et, entity_type root
              WHERE (root.id::text = :t OR root.slug = :t)
                AND et.hierarchy <@ root.hierarchy
            )
        """
        params["t"] = entity_type

    result = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id, e.canonical AS title, e.summary AS snippet,
                   1 - (e.summary_embedding <=> CAST(:embedding AS vector)) AS score,
                   et.slug AS type_slug, e.iri
            FROM entity e
            JOIN entity_type et ON et.id = e.type_id
            WHERE e.workspace_id = :workspace_id
              AND e.deleted_at IS NULL AND e.merged_into_id IS NULL
              AND e.summary_embedding IS NOT NULL
              {extra}
            ORDER BY e.summary_embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        SearchResult(
            kind="entity", id=r["id"], title=r["title"], snippet=r["snippet"] or "",
            score=float(r["score"]),
            payload={"type": r["type_slug"], "iri": r["iri"]},
        )
        for r in result.mappings()
    ]


async def _entity_text(
    session: AsyncSession, workspace_id: str, query: str, entity_type: str | None,
) -> list[SearchResult]:
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "q": query,
        "like_q": f"%{query}%",
        "limit": 50,
    }
    extra = ""
    if entity_type:
        extra = """
            AND e.type_id IN (
              SELECT et.id FROM entity_type et, entity_type root
              WHERE (root.id::text = :t OR root.slug = :t)
                AND et.hierarchy <@ root.hierarchy
            )
        """
        params["t"] = entity_type

    result = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id, e.canonical AS title, e.summary AS snippet,
                   GREATEST(
                     similarity(e.canonical, :q),
                     COALESCE((SELECT MAX(similarity(a, :q)) FROM unnest(e.aliases) a), 0)
                   ) AS score,
                   et.slug AS type_slug, e.iri
            FROM entity e
            JOIN entity_type et ON et.id = e.type_id
            WHERE e.workspace_id = :workspace_id
              AND e.deleted_at IS NULL AND e.merged_into_id IS NULL
              AND (e.canonical ILIKE :like_q OR :q = ANY(e.aliases)
                   OR similarity(e.canonical, :q) > 0.2)
              {extra}
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        SearchResult(
            kind="entity", id=r["id"], title=r["title"], snippet=r["snippet"] or "",
            score=float(r["score"]),
            payload={"type": r["type_slug"], "iri": r["iri"]},
        )
        for r in result.mappings()
    ]


async def _edge_vector(
    session: AsyncSession, workspace_id: str, embedding: list[float] | None,
    as_of_valid: str | None, *, principal: Principal | None = None,
) -> list[SearchResult]:
    if embedding is None:
        return []
    valid_clause = "e.valid_time @> now()" if not as_of_valid else "e.valid_time @> CAST(:vt AS timestamptz)"
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "embedding": to_pg_vector(embedding),
        "limit": 50,
    }
    if as_of_valid:
        params["vt"] = as_of_valid

    acl_filter = ""
    if principal is not None:
        clause = edge_visibility_clause(principal, edge_alias="e")
        acl_filter = f"AND ({clause.text})"
        for k, v in clause._bindparams.items():
            params[k] = v.value

    result = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id, e.fact AS title, e.fact AS snippet,
                   1 - (e.fact_embedding <=> CAST(:embedding AS vector)) AS score,
                   s.canonical AS subject_name, s.id::text AS subject_id,
                   o.canonical AS object_name, o.id::text AS object_id,
                   rt.slug AS predicate, lower(e.valid_time)::text AS valid_from
            FROM edge e
            JOIN entity s ON s.id = e.subject_id
            JOIN entity o ON o.id = e.object_id
            JOIN relation_type rt ON rt.id = e.predicate_id
            WHERE e.workspace_id = :workspace_id
              AND upper(e.sys_time) = 'infinity'
              AND {valid_clause}
              AND e.fact_embedding IS NOT NULL
              {acl_filter}
            ORDER BY e.fact_embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        SearchResult(
            kind="edge", id=r["id"], title=r["title"], snippet=r["snippet"],
            score=float(r["score"]),
            payload={
                "subject_id": r["subject_id"], "subject": r["subject_name"],
                "object_id": r["object_id"], "object": r["object_name"],
                "predicate": r["predicate"], "valid_from": r["valid_from"],
            },
        )
        for r in result.mappings()
    ]


async def _edge_text(
    session: AsyncSession, workspace_id: str, query: str,
    as_of_valid: str | None, *, principal: Principal | None = None,
) -> list[SearchResult]:
    """Trigram + ILIKE fallback for edges.

    Vector search needs an embedding, which needs an OpenAI key. This
    text-based path lets the demo (and any deploy without embeddings)
    surface relevant edges by their fact text. The ACL filter applies
    here too, so a user without identity sees nothing extra.
    """
    if not query.strip():
        return []
    valid_clause = "e.valid_time @> now()" if not as_of_valid else "e.valid_time @> CAST(:vt AS timestamptz)"
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "q": query,
        "like_q": f"%{query}%",
        "limit": 50,
    }
    if as_of_valid:
        params["vt"] = as_of_valid

    acl_filter = ""
    if principal is not None:
        clause = edge_visibility_clause(principal, edge_alias="e")
        acl_filter = f"AND ({clause.text})"
        for k, v in clause._bindparams.items():
            params[k] = v.value

    result = await session.execute(
        text(
            f"""
            SELECT e.id::text AS id, e.fact AS title, e.fact AS snippet,
                   similarity(e.fact, :q) AS score,
                   s.canonical AS subject_name, s.id::text AS subject_id,
                   o.canonical AS object_name, o.id::text AS object_id,
                   rt.slug AS predicate, lower(e.valid_time)::text AS valid_from
            FROM edge e
            JOIN entity s ON s.id = e.subject_id
            JOIN entity o ON o.id = e.object_id
            JOIN relation_type rt ON rt.id = e.predicate_id
            WHERE e.workspace_id = :workspace_id
              AND upper(e.sys_time) = 'infinity'
              AND {valid_clause}
              AND e.fact ILIKE :like_q
              {acl_filter}
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        SearchResult(
            kind="edge", id=r["id"], title=r["title"], snippet=r["snippet"],
            score=float(r["score"]),
            payload={
                "subject_id": r["subject_id"], "subject": r["subject_name"],
                "object_id": r["object_id"], "object": r["object_name"],
                "predicate": r["predicate"], "valid_from": r["valid_from"],
            },
        )
        for r in result.mappings()
    ]


async def _episode_vector(
    session: AsyncSession, workspace_id: str, embedding: list[float] | None,
    *, principal: Principal | None = None,
) -> list[SearchResult]:
    if embedding is None:
        return []
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "embedding": to_pg_vector(embedding),
        "limit": 30,
    }
    acl_filter = ""
    if principal is not None:
        clause = episode_visibility_clause(principal, episode_alias="episode")
        acl_filter = f"AND ({clause.text})"
        for k, v in clause._bindparams.items():
            params[k] = v.value
    result = await session.execute(
        text(
            f"""
            SELECT episode.id::text, source_kind, source_ref,
                   occurred_at::text AS occurred_at,
                   substring(COALESCE(content_text, '') for 400) AS snippet,
                   1 - (content_embedding <=> CAST(:embedding AS vector)) AS score
            FROM episode
            WHERE workspace_id = :workspace_id AND content_embedding IS NOT NULL
              {acl_filter}
            ORDER BY content_embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        SearchResult(
            kind="episode", id=r["id"], title=r["source_kind"],
            snippet=r["snippet"] or "", score=float(r["score"]),
            payload={"source_ref": r["source_ref"], "occurred_at": r["occurred_at"]},
        )
        for r in result.mappings()
    ]


async def _episode_text(
    session: AsyncSession, workspace_id: str, query: str,
    *, principal: Principal | None = None,
) -> list[SearchResult]:
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "q": query,
        "like_q": f"%{query}%",
        "limit": 30,
    }
    acl_filter = ""
    if principal is not None:
        clause = episode_visibility_clause(principal, episode_alias="episode")
        acl_filter = f"AND ({clause.text})"
        for k, v in clause._bindparams.items():
            params[k] = v.value
    result = await session.execute(
        text(
            f"""
            SELECT episode.id::text, source_kind, source_ref,
                   occurred_at::text AS occurred_at,
                   substring(COALESCE(content_text, '') for 400) AS snippet,
                   similarity(COALESCE(content_text, ''), :q) AS score
            FROM episode
            WHERE workspace_id = :workspace_id
              AND content_text ILIKE :like_q
              {acl_filter}
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        SearchResult(
            kind="episode", id=r["id"], title=r["source_kind"],
            snippet=r["snippet"] or "", score=float(r["score"]),
            payload={"source_ref": r["source_ref"], "occurred_at": r["occurred_at"]},
        )
        for r in result.mappings()
    ]


async def _block_text(
    session: AsyncSession, workspace_id: str, query: str,
) -> list[SearchResult]:
    result = await session.execute(
        text(
            """
            WITH q AS (SELECT plainto_tsquery('simple', :q) AS tsq)
            SELECT b.id::text, b.document_id::text AS document_id,
                   ts_rank(b.search_tsv, (SELECT tsq FROM q)) AS score,
                   substring(COALESCE(b.search_text, '') for 400) AS snippet,
                   e.canonical AS document_title
            FROM block b
            JOIN document d ON d.id = b.document_id
            JOIN entity e ON e.id = d.entity_id
            WHERE b.workspace_id = :workspace_id
              AND b.deleted_at IS NULL
              AND b.search_tsv @@ (SELECT tsq FROM q)
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        {"workspace_id": workspace_id, "q": query, "limit": 30},
    )
    return [
        SearchResult(
            kind="block", id=r["id"], title=r["document_title"],
            snippet=r["snippet"] or "", score=float(r["score"]),
            payload={"document_id": r["document_id"]},
        )
        for r in result.mappings()
    ]


# ---------------------------------------------------------------------------
# Fusion + diversity
# ---------------------------------------------------------------------------

def _rrf(lists: list[list[SearchResult]], *, k: int = 60) -> list[SearchResult]:
    """Reciprocal Rank Fusion. Preserves the best payload per key."""
    scores: dict[str, float] = {}
    items: dict[str, SearchResult] = {}
    for results in lists:
        for rank, res in enumerate(results, start=1):
            contribution = 1.0 / (k + rank)
            key = res.key()
            scores[key] = scores.get(key, 0.0) + contribution
            if key not in items or res.score > items[key].score:
                items[key] = res

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    out: list[SearchResult] = []
    for key, score in ranked:
        item = items[key]
        item.score = score
        out.append(item)
    return out


def _mmr(results: list[SearchResult], *, k: int, lambda_: float = 0.7) -> list[SearchResult]:
    """Diversify by MMR over textual Jaccard between snippets."""
    if len(results) <= k:
        return results

    def bag(r: SearchResult) -> set[str]:
        words = (r.title + " " + r.snippet).lower().split()
        return {w for w in words if len(w) > 3}

    chosen: list[SearchResult] = []
    remaining = list(results)
    while remaining and len(chosen) < k:
        best_idx = 0
        best_score = -math.inf
        for i, cand in enumerate(remaining):
            sim_to_chosen = max(
                (_jaccard(bag(cand), bag(other)) for other in chosen),
                default=0.0,
            )
            mmr = lambda_ * cand.score - (1 - lambda_) * sim_to_chosen
            if mmr > best_score:
                best_idx = i
                best_score = mmr
        chosen.append(remaining.pop(best_idx))
    return chosen


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Graph 1-hop expansion
# ---------------------------------------------------------------------------

async def _graph_expand(
    session: AsyncSession,
    workspace_id: str,
    results: list[SearchResult],
    *,
    limit: int,
    principal: Principal | None = None,
) -> list[SearchResult]:
    entity_ids = [r.id for r in results if r.kind == "entity"][:10]
    if not entity_ids:
        return results

    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "ids": entity_ids,
        "limit": limit,
    }
    acl_filter = ""
    if principal is not None:
        clause = edge_visibility_clause(principal, edge_alias="e")
        acl_filter = f"AND ({clause.text})"
        for k, v in clause._bindparams.items():
            params[k] = v.value

    expansion = await session.execute(
        text(
            f"""
            SELECT e.id::text AS edge_id, e.fact AS fact,
                   s.canonical AS s, o.canonical AS o,
                   rt.slug AS p, s.id::text AS subject_id, o.id::text AS object_id
            FROM edge e
            JOIN entity s ON s.id = e.subject_id
            JOIN entity o ON o.id = e.object_id
            JOIN relation_type rt ON rt.id = e.predicate_id
            WHERE e.workspace_id = :workspace_id
              AND upper(e.sys_time) = 'infinity'
              AND e.valid_time @> now()
              AND (e.subject_id = ANY(:ids) OR e.object_id = ANY(:ids))
              {acl_filter}
            LIMIT :limit
            """
        ),
        params,
    )
    for r in expansion.mappings():
        item = SearchResult(
            kind="edge", id=r["edge_id"], title=r["fact"], snippet=r["fact"],
            score=0.1,
            payload={
                "subject_id": r["subject_id"], "subject": r["s"],
                "object_id": r["object_id"], "object": r["o"],
                "predicate": r["p"], "via": "graph_expand",
            },
        )
        if not any(x.key() == item.key() for x in results):
            results.append(item)
    return results
