"""Episode → entities/edges extraction pipeline.

1. Load ontology snapshot.
2. Run structured-output LLM to extract entities + facts grounded in the ontology.
3. Resolve each extracted entity to an existing one (alias + similarity) or create a new one.
4. For each fact, resolve subject + object, validate domain/range, and add the edge.
5. When workspace.settings.ontology_mode is "flexible" or "auto", allow the extractor to
   introduce new entity/relation types on the fly.

Runs as an Arq job. Episode rows carry ``processing_status`` so the UI
can show progress.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import entity_resolver as resolver_mod
from app.domain import ontology as ontology_mod
from app.domain import provenance as prov_mod
from app.llm.embedding import get_embedding_client
from app.llm.provider import get_llm
from app.llm.vector_utils import to_pg_vector

log = get_logger(__name__)


class ExtractedEntity(BaseModel):
    local_id: str = Field(..., description="A label unique within this extraction (e.g. 'alice', 'acme').")
    name: str = Field(..., description="Canonical name.")
    type_slug: str = Field(..., description="Existing or newly-proposed entity type slug.")
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = Field(default=None)
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedEdge(BaseModel):
    subject_local_id: str
    predicate_slug: str
    object_local_id: str
    fact: str = Field(..., max_length=300)
    valid_from: str | None = Field(default=None, description="ISO-8601 date or date-time.")
    valid_to: str | None = Field(default=None, description="ISO-8601, inclusive of end.")
    confidence: float | None = Field(default=None, ge=0, le=1)


class Extraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


SYSTEM_PROMPT = """You extract entities and factual relationships from the text given.

Rules:
- Use `local_id` labels to connect the same entity across facts — keep them short and lowercase.
- Prefer existing entity and relation types (provided below). Only introduce new slugs if the existing ontology truly cannot express the content.
- Facts must be grounded in the text. Do NOT invent relationships.
- Keep `fact` short and natural-language, e.g. "Alice works at Acme".

Date / valid_time rules:
- Parse dates explicit in the text into ISO-8601 and put them in `valid_from` / `valid_to`.
- If the fact is ongoing/present-tense (e.g. "Lina leads product"), set `valid_from` to the REFERENCE_TIME provided below — that's when the document was authored.
- If the text says a transition happens on a specific date (e.g. "effective 2026-05-21, X replaces Y"), set the NEW fact's `valid_from` to that date.
- Leave `valid_from` null only if the fact has no date AND no reference time was provided."""


@dataclass
class ExtractionResult:
    episode_id: str
    created_entities: list[str] = field(default_factory=list)
    resolved_entities: list[str] = field(default_factory=list)
    created_edges: list[str] = field(default_factory=list)
    pending_facts: list[str] = field(default_factory=list)
    rejected_facts: list[str] = field(default_factory=list)
    ontology_extended_types: list[str] = field(default_factory=list)
    ontology_extended_relations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    prov_activity_id: str | None = None


async def process_episode(
    session: AsyncSession,
    *,
    episode_id: str,
    actor_id: str | None = None,
) -> ExtractionResult:
    result = ExtractionResult(episode_id=episode_id)

    episode = await _load_episode(session, episode_id)
    if not episode:
        result.errors.append("episode not found")
        return result

    workspace_id = episode["workspace_id"]
    await _mark_status(session, episode_id, "processing")

    settings = get_settings()
    activity_id = await prov_mod.start_activity(
        session,
        workspace_id=workspace_id,
        kind="extraction",
        agent_kind="llm",
        agent_ref=settings.llm_model,
        agent_version=None,
        inputs={"episode_id": episode_id},
    )
    result.prov_activity_id = activity_id

    # Stamp the episode itself with the activity that processed it.
    await session.execute(
        text(
            """
            UPDATE episode SET prov_activity_id = COALESCE(prov_activity_id, :a)
            WHERE id = :id
            """
        ),
        {"id": episode_id, "a": activity_id},
    )

    settings_row = await session.execute(
        text("SELECT settings FROM workspace WHERE id = :id"),
        {"id": workspace_id},
    )
    ws_settings = settings_row.scalar_one()
    ontology_mode = (ws_settings or {}).get("ontology_mode", "strict")

    # Ensure we have an embedding for the episode text, so retrieval can find it later.
    if episode["content_text"] and not episode["has_embedding"]:
        try:
            vec = await get_embedding_client().embed_one(episode["content_text"])
            await session.execute(
                text(
                    """
                    UPDATE episode SET content_embedding = CAST(:embedding AS vector)
                    WHERE id = :id
                    """
                ),
                {"id": episode_id, "embedding": to_pg_vector(vec)},
            )
        except Exception as exc:
            log.warning("extraction.embedding_failed", episode_id=episode_id, error=str(exc))

    snapshot = await ontology_mod.snapshot(session)

    try:
        extracted = await _run_llm(
            snapshot=snapshot,
            text_=episode["content_text"] or "",
            reference_time=episode.get("occurred_at"),
        )
    except Exception as exc:
        await _mark_status(session, episode_id, "failed", error=str(exc))
        result.errors.append(f"llm: {exc}")
        return result

    # Step 1: ensure all referenced types exist (respecting mode).
    type_slugs = {e.type_slug for e in extracted.entities}
    relation_slugs = {e.predicate_slug for e in extracted.edges}

    if ontology_mode in ("flexible", "auto"):
        await _extend_ontology(
            session,
            workspace_id=workspace_id,
            snapshot=snapshot,
            type_slugs=type_slugs,
            relation_slugs=relation_slugs,
            result=result,
            actor_id=actor_id,
        )
        # Refresh snapshot after creating types.
        snapshot = await ontology_mod.snapshot(session)

    async def _populate_external_refs(entity_id: str, props: dict[str, Any]) -> None:
        """Mirror well-known property keys onto entity_external_ref so
        Tier-1 resolution short-circuits next time we see the same
        identifier in another extraction.
        """
        for prop, kind in (
            ("email", "email"),
            ("slug", "slug"),
            ("wikidata", "wikidata"),
            ("wikidata_id", "wikidata"),
        ):
            value = props.get(prop)
            if isinstance(value, str) and value.strip():
                try:
                    await resolver_mod.add_external_ref(
                        session,
                        workspace_id=workspace_id,
                        entity_id=entity_id,
                        kind=kind,
                        value=value.strip(),
                    )
                except Exception as exc:
                    log.warning(
                        "extraction.external_ref_failed",
                        entity_id=entity_id, kind=kind, error=str(exc),
                    )

    # Step 2: resolve/create entities via the three-tier cascade.
    local_to_entity: dict[str, str] = {}
    for e in extracted.entities:
        type_def = snapshot.type_by_slug(e.type_slug)
        if not type_def:
            result.errors.append(f"unknown type: {e.type_slug}")
            continue

        # Extracted-prop external_refs feed Tier-1 of the resolver.
        candidate_refs: list[resolver_mod.ExternalRef] = []
        for prop, kind in (
            ("email", "email"),
            ("slug", "slug"),
            ("wikidata", "wikidata"),
            ("wikidata_id", "wikidata"),
        ):
            v = e.properties.get(prop) if isinstance(e.properties, dict) else None
            if isinstance(v, str) and v.strip():
                candidate_refs.append(
                    resolver_mod.ExternalRef(kind=kind, value=v.strip())
                )

        candidate = resolver_mod.EntityCandidate(
            canonical=e.name,
            type_slug=e.type_slug,
            summary=e.summary,
            aliases=list(e.aliases),
            external_refs=candidate_refs,
        )
        resolution = await resolver_mod.resolve(
            session, workspace_id=workspace_id, candidate=candidate
        )

        if resolution.decision == "match" and resolution.entity_id:
            existing = await entity_mod.get(session, resolution.entity_id)
            if existing:
                local_to_entity[e.local_id] = existing.id
                result.resolved_entities.append(existing.id)
                current_aliases = set(existing.aliases)
                new_aliases = [
                    a for a in e.aliases
                    if a not in current_aliases and a != existing.canonical
                ]
                if new_aliases:
                    await session.execute(
                        text(
                            """
                            UPDATE entity SET aliases = (
                              SELECT array_agg(DISTINCT x) FROM unnest(aliases || :new) x
                            )
                            WHERE id = :id
                            """
                        ),
                        {"id": existing.id, "new": new_aliases},
                    )
                # Make sure any newly-discovered external_refs are also
                # attached to the matched entity (idempotent on conflict).
                await _populate_external_refs(existing.id, e.properties or {})
                continue

        # Resolver said "uncertain" — there's a plausible-but-not-confident
        # match. Linking silently would risk merging two real entities;
        # creating silently would litter the graph with duplicates. The
        # least-surprising choice: link to the best candidate so downstream
        # edges have a target, AND write an audit row so a human can
        # confirm or split later.
        if (
            resolution.decision == "uncertain"
            and resolution.entity_id is not None
        ):
            best = await entity_mod.get(session, resolution.entity_id)
            if best:
                local_to_entity[e.local_id] = best.id
                result.resolved_entities.append(best.id)
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_log
                          (workspace_id, actor_kind, actor_id, action,
                           target_kind, target_id, diff)
                        VALUES (CAST(:ws AS uuid), 'system',
                                CAST(:actor AS uuid), 'entity.resolver.uncertain',
                                'entity', CAST(:id AS uuid),
                                jsonb_build_object(
                                  'tier', CAST(:tier AS text),
                                  'score', CAST(:score AS real),
                                  'rationale', CAST(:rationale AS text),
                                  'candidate_name', CAST(:cand_name AS text)
                                ))
                        """
                    ),
                    {
                        "ws": workspace_id,
                        "actor": actor_id,
                        "id": best.id,
                        "tier": resolution.tier,
                        "score": float(resolution.score),
                        "rationale": resolution.rationale,
                        "cand_name": e.name,
                    },
                )
                log.warning(
                    "extraction.resolver_uncertain",
                    candidate=e.name,
                    matched_to=best.id,
                    tier=resolution.tier,
                    score=resolution.score,
                )
                await _populate_external_refs(best.id, e.properties or {})
                continue

        # Create new entity.
        try:
            created = await entity_mod.create(
                session,
                workspace_id=workspace_id,
                type_ref=e.type_slug,
                canonical=e.name,
                aliases=list(e.aliases),
                summary=e.summary,
                props=e.properties,
                created_by=actor_id,
            )
            local_to_entity[e.local_id] = created.id
            result.created_entities.append(created.id)
            await _populate_external_refs(created.id, e.properties or {})
        except Exception as exc:
            result.errors.append(f"entity {e.name}: {exc}")

    # Default for valid_from when the LLM didn't extract an explicit date
    # from the text: anchor to the source episode's occurred_at (the doc's
    # Drive modifiedTime). That's the Graphiti pattern — "if no event-time
    # was stated, use the document's own reference time, not ingestion now()."
    # Falls back to now() only if the episode also has no occurred_at.
    episode_occurred_at = _parse_iso(episode["occurred_at"]) if episode.get("occurred_at") else None

    # Step 3: create edges.
    for ex in extracted.edges:
        subj = local_to_entity.get(ex.subject_local_id)
        obj = local_to_entity.get(ex.object_local_id)
        if not subj or not obj:
            result.errors.append(f"edge missing endpoint: {ex.fact}")
            continue
        relation = snapshot.relation_by_slug(ex.predicate_slug)
        if not relation:
            result.errors.append(f"unknown relation: {ex.predicate_slug}")
            continue
        try:
            valid_from_dt = _parse_iso(ex.valid_from) if ex.valid_from else None
            if valid_from_dt is None:
                # No date in the LLM output — anchor to the source doc.
                valid_from_dt = episode_occurred_at
            valid_to_dt = _parse_iso(ex.valid_to) if ex.valid_to else None
            # If the LLM didn't provide a confidence, default to 1.0 so
            # the fact bypasses threshold review (preserves prior behavior
            # for ontologies where confidence isn't surfaced).
            confidence = ex.confidence if ex.confidence is not None else 1.0
            write = await edge_mod.propose_fact(
                session,
                workspace_id=workspace_id,
                subject_id=subj,
                predicate=relation.id,
                object_id=obj,
                fact=ex.fact,
                valid_from=valid_from_dt,
                valid_to=valid_to_dt,
                source_id=episode_id,
                source_kind="episode",
                confidence=confidence,
                created_by=actor_id,
                prov_activity_id=activity_id,
            )
            if write.kind == "edge" and write.edge is not None:
                result.created_edges.append(write.edge.id)
            elif write.kind == "pending" and write.pending_fact_id:
                result.pending_facts.append(write.pending_fact_id)
            elif write.kind == "rejected" and write.pending_fact_id:
                result.rejected_facts.append(write.pending_fact_id)
        except Exception as exc:
            result.errors.append(f"edge {ex.fact}: {exc}")

    status: Literal["completed", "failed"] = "completed" if not result.errors or result.created_edges or result.created_entities else "failed"
    await _mark_status(session, episode_id, status, error="\n".join(result.errors) if result.errors else None)

    await prov_mod.end_activity(
        session,
        activity_id,
        outputs={
            "created_edges": result.created_edges,
            "pending_facts": result.pending_facts,
            "rejected_facts": result.rejected_facts,
            "created_entities": result.created_entities,
        },
    )

    log.info(
        "extraction.episode.done",
        episode_id=episode_id,
        created_entities=len(result.created_entities),
        resolved=len(result.resolved_entities),
        created_edges=len(result.created_edges),
        pending_facts=len(result.pending_facts),
        rejected_facts=len(result.rejected_facts),
        errors=len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _run_llm(
    *,
    snapshot: ontology_mod.OntologySnapshot,
    text_: str,
    reference_time: str | None = None,
) -> Extraction:
    existing_types = "\n".join(
        f"- {t.slug}"
        + (f" (extends {next((x.slug for x in snapshot.types if x.id == t.extends_id), 'thing')})"
           if t.extends_id else "")
        + (f" — {t.description}" if t.description else "")
        for t in snapshot.types
    ) or "(none)"
    existing_rels = "\n".join(
        f"- {r.slug}: {_slug_by_id(snapshot, r.domain_type_id) or 'thing'} → {_slug_by_id(snapshot, r.range_type_id) or 'thing'}"
        for r in snapshot.relations
    ) or "(none)"

    ref_block = (
        f"REFERENCE_TIME (the document's authored date — use this as valid_from "
        f"for any ongoing/present-tense fact that doesn't carry its own date):\n"
        f"{reference_time}\n\n"
        if reference_time else ""
    )

    user_prompt = (
        "Available entity types:\n"
        f"{existing_types}\n\n"
        "Available relation types:\n"
        f"{existing_rels}\n\n"
        f"{ref_block}"
        "Text to extract from:\n---\n"
        f"{text_}\n---"
    )
    llm = get_llm()
    return await llm.structured(
        schema=Extraction, system=SYSTEM_PROMPT, user=user_prompt,
        temperature=0.1, max_tokens=16000,
    )


async def _extend_ontology(
    session: AsyncSession,
    *,
    workspace_id: str,
    snapshot: ontology_mod.OntologySnapshot,
    type_slugs: set[str],
    relation_slugs: set[str],
    result: ExtractionResult,
    actor_id: str | None,
) -> None:
    existing_type_slugs = {t.slug for t in snapshot.types}
    existing_relation_slugs = {r.slug for r in snapshot.relations}

    for slug in type_slugs - existing_type_slugs:
        try:
            created = await ontology_mod.create_entity_type(
                session,
                workspace_id=workspace_id,
                name=_humanize(slug),
                slug=slug,
                extends="thing",
                description="Auto-discovered during extraction.",
                ui_hints={"proposed_by": actor_id or "extractor"},
            )
            result.ontology_extended_types.append(created.slug)
        except Exception as exc:
            result.errors.append(f"auto-type {slug}: {exc}")

    for slug in relation_slugs - existing_relation_slugs:
        try:
            created = await ontology_mod.create_relation_type(
                session,
                workspace_id=workspace_id,
                name=_humanize(slug),
                slug=slug,
                description="Auto-discovered during extraction.",
                domain="thing",
                range_="thing",
                ui_hints={"proposed_by": actor_id or "extractor"},
            )
            result.ontology_extended_relations.append(created.slug)
        except Exception as exc:
            result.errors.append(f"auto-relation {slug}: {exc}")


def _slug_by_id(snapshot: ontology_mod.OntologySnapshot, type_id: str | None) -> str | None:
    if not type_id:
        return None
    t = snapshot.type_by_id(type_id)
    return t.slug if t else None


def _humanize(slug: str) -> str:
    return slug.replace("_", " ").title()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


async def _load_episode(session: AsyncSession, episode_id: str) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            """
            SELECT ep.id::text, ep.workspace_id::text, ep.source_kind,
                   ep.occurred_at::text,
                   ep.content, ep.content_text,
                   (ep.content_embedding IS NOT NULL) AS has_embedding
            FROM episode ep
            WHERE ep.id = :id
            """
        ),
        {"id": episode_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _mark_status(
    session: AsyncSession,
    episode_id: str,
    status: str,
    error: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE episode
            SET processing_status = :status,
                processing_error = :error
            WHERE id = :id
            """
        ),
        {"id": episode_id, "status": status, "error": error},
    )
