"""LLM-driven ontology proposer.

Analyzes a sample of text (episodes or raw strings) and proposes entity
and relation types with JSON Schemas. The proposal can be rendered for
human review or applied directly when the workspace's ontology_mode is
"auto".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain import ontology as ontology_mod
from app.llm.provider import get_llm

log = get_logger(__name__)


class ProposedProperty(BaseModel):
    name: str = Field(..., description="Machine-friendly property name in snake_case.")
    label: str = Field(..., description="Human-readable label.")
    type: Literal["string", "number", "integer", "boolean", "date", "date-time", "enum"] = Field(...)
    enum_values: list[str] | None = Field(default=None)
    required: bool = Field(default=False)


class ProposedEntityType(BaseModel):
    slug: str = Field(..., description="snake_case slug, unique within the ontology.")
    name: str = Field(..., description="Human label (singular, Title Case).")
    extends: str | None = Field(
        default=None,
        description="Parent type slug. Use an existing type when possible, otherwise null.",
    )
    description: str = Field(..., max_length=200)
    properties: list[ProposedProperty] = Field(default_factory=list)


class ProposedRelationType(BaseModel):
    slug: str
    name: str
    description: str = Field(..., max_length=200)
    domain: str = Field(..., description="Subject type slug.")
    range: str = Field(..., description="Object type slug.")
    cardinality_subject: Literal["one", "many"] = "many"
    cardinality_object: Literal["one", "many"] = "many"
    temporal: bool = False
    symmetric: bool = False
    transitive: bool = False
    high_stakes: bool = False


class OntologyProposal(BaseModel):
    rationale: str = Field(..., max_length=600)
    entity_types: list[ProposedEntityType]
    relation_types: list[ProposedRelationType]


@dataclass
class ApplyResult:
    created_types: list[str] = field(default_factory=list)
    created_relations: list[str] = field(default_factory=list)
    skipped_types: list[str] = field(default_factory=list)
    skipped_relations: list[str] = field(default_factory=list)


SYSTEM_PROMPT = """You are an ontology architect for a knowledge memory platform.

Given a sample of text (meeting notes, emails, documents, conversation transcripts), propose an ontology that captures the main entities and relationships.

Rules:
- Prefer reusing the provided existing entity and relation types before inventing new ones.
- When introducing new types, anchor them under an existing type via `extends` when possible (e.g. a new "Engineer" type should extend "person" if "person" exists).
- Property names must be snake_case; types must follow the JSON Schema subset: string, number, integer, boolean, date, date-time, enum.
- Keep the ontology tight. Aim for 3-8 new entity types and 4-10 new relation types max per proposal.
- Use `high_stakes = true` only for relations whose object can meaningfully change over time and where contradictions would matter (e.g. employment, residence, ownership, management).
- Use `symmetric = true` only for truly bidirectional relations (e.g. "knows", "spouse_of").
- Use `transitive = true` for compositional relations (e.g. "part_of", "located_in")."""


async def propose_ontology(
    session: AsyncSession,
    *,
    workspace_id: str,
    samples: list[str],
    max_samples: int = 10,
    max_sample_chars: int = 4000,
) -> OntologyProposal:
    existing = await ontology_mod.snapshot(session)

    clipped = [s[:max_sample_chars] for s in samples[:max_samples]]

    user_prompt = _build_user_prompt(existing=existing, samples=clipped)

    llm = get_llm()
    proposal = await llm.structured(
        schema=OntologyProposal,
        system=SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=3000,
    )

    log.info(
        "ontology.proposal.generated",
        workspace_id=workspace_id,
        types=len(proposal.entity_types),
        relations=len(proposal.relation_types),
    )
    return proposal


async def apply_proposal(
    session: AsyncSession,
    *,
    workspace_id: str,
    proposal: OntologyProposal,
    actor_id: str | None = None,
    allow_replace: bool = False,
) -> ApplyResult:
    """Apply a proposal to the workspace.

    Existing slugs are skipped unless ``allow_replace`` is true (which
    updates schemas/ui_hints but never renames system types).
    """
    existing = await ontology_mod.snapshot(session)
    existing_type_slugs = {t.slug for t in existing.types}
    existing_relation_slugs = {r.slug for r in existing.relations}

    result = ApplyResult()

    # Entity types first, topologically ordered by ``extends``.
    ordered = _topo_ordered(proposal.entity_types)
    for proposed in ordered:
        if proposed.slug in existing_type_slugs and not allow_replace:
            result.skipped_types.append(proposed.slug)
            continue
        schema = _properties_to_json_schema(proposed.properties)
        try:
            created = await ontology_mod.create_entity_type(
                session,
                workspace_id=workspace_id,
                name=proposed.name,
                slug=proposed.slug,
                extends=proposed.extends,
                schema=schema,
                description=proposed.description,
                ui_hints={"proposed_by": actor_id or "agent"},
            )
            result.created_types.append(created.slug)
            existing_type_slugs.add(created.slug)
        except Exception as exc:
            log.warning("ontology.apply.type_failed", slug=proposed.slug, error=str(exc))
            result.skipped_types.append(proposed.slug)

    for proposed in proposal.relation_types:
        if proposed.slug in existing_relation_slugs and not allow_replace:
            result.skipped_relations.append(proposed.slug)
            continue
        try:
            created = await ontology_mod.create_relation_type(
                session,
                workspace_id=workspace_id,
                name=proposed.name,
                slug=proposed.slug,
                description=proposed.description,
                domain=proposed.domain,
                range_=proposed.range,
                cardinality_subject=proposed.cardinality_subject,
                cardinality_object=proposed.cardinality_object,
                temporal=proposed.temporal,
                symmetric=proposed.symmetric,
                transitive=proposed.transitive,
                high_stakes=proposed.high_stakes,
                ui_hints={"proposed_by": actor_id or "agent"},
            )
            result.created_relations.append(created.slug)
            existing_relation_slugs.add(created.slug)
        except Exception as exc:
            log.warning("ontology.apply.relation_failed", slug=proposed.slug, error=str(exc))
            result.skipped_relations.append(proposed.slug)

    # Audit log entry summarising the application.
    await session.execute(
        text(
            """
            INSERT INTO audit_log (workspace_id, actor_kind, actor_id, action,
                                   target_kind, target_id, diff)
            VALUES (:workspace_id,
                    CASE WHEN :actor_id IS NULL THEN 'system' ELSE 'agent' END,
                    :actor_id,
                    'ontology.apply_proposal', 'ontology', NULL,
                    CAST(:diff AS jsonb))
            """
        ),
        {
            "workspace_id": workspace_id,
            "actor_id": actor_id,
            "diff": _json({
                "created_types": result.created_types,
                "created_relations": result.created_relations,
                "skipped_types": result.skipped_types,
                "skipped_relations": result.skipped_relations,
            }),
        },
    )

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_user_prompt(*, existing: ontology_mod.OntologySnapshot, samples: list[str]) -> str:
    existing_types = "\n".join(
        f"- {t.slug}"
        + (f" (extends {next((x.slug for x in existing.types if x.id == t.extends_id), 'thing')})"
           if t.extends_id else "")
        + (f" — {t.description}" if t.description else "")
        for t in existing.types
    )
    existing_rels = "\n".join(
        f"- {r.slug}: {_domain_slug(r, existing)} → {_range_slug(r, existing)}"
        + (f" ({r.description})" if r.description else "")
        for r in existing.relations
    )
    samples_text = "\n\n---\n\n".join(samples)
    return (
        "Existing entity types:\n"
        f"{existing_types or '(none)'}\n\n"
        "Existing relation types:\n"
        f"{existing_rels or '(none)'}\n\n"
        "Samples:\n"
        f"{samples_text}"
    )


def _domain_slug(r: ontology_mod.RelationType, snap: ontology_mod.OntologySnapshot) -> str:
    if not r.domain_type_id:
        return "thing"
    t = snap.type_by_id(r.domain_type_id)
    return t.slug if t else "thing"


def _range_slug(r: ontology_mod.RelationType, snap: ontology_mod.OntologySnapshot) -> str:
    if not r.range_type_id:
        return "thing"
    t = snap.type_by_id(r.range_type_id)
    return t.slug if t else "thing"


def _topo_ordered(types: list[ProposedEntityType]) -> list[ProposedEntityType]:
    by_slug = {t.slug: t for t in types}
    visited: set[str] = set()
    out: list[ProposedEntityType] = []

    def visit(t: ProposedEntityType) -> None:
        if t.slug in visited:
            return
        if t.extends and t.extends in by_slug:
            visit(by_slug[t.extends])
        visited.add(t.slug)
        out.append(t)

    for t in types:
        visit(t)
    return out


def _properties_to_json_schema(properties: list[ProposedProperty]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in properties:
        if p.type == "enum":
            props[p.name] = {
                "type": "string",
                "enum": p.enum_values or [],
                "title": p.label,
            }
        elif p.type == "date":
            props[p.name] = {"type": "string", "format": "date", "title": p.label}
        elif p.type == "date-time":
            props[p.name] = {"type": "string", "format": "date-time", "title": p.label}
        else:
            props[p.name] = {"type": p.type, "title": p.label}
        if p.required:
            required.append(p.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return schema


def _json(value: Any) -> str:
    import json
    return json.dumps(value)
