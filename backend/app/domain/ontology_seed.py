"""Load the built-in ontology from seeds/ontology.yaml into a workspace.

Idempotent by (workspace_id, slug): re-running updates existing system types
and relations to match the YAML.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_SEED_PATH = Path("/seeds/ontology.yaml")


def load_seed(path: Path | None = None) -> dict[str, Any]:
    seed_path = path or DEFAULT_SEED_PATH
    if not seed_path.exists():
        raise FileNotFoundError(f"ontology seed not found at {seed_path}")
    with seed_path.open() as f:
        data = yaml.safe_load(f)
    assert "types" in data and "relations" in data, "seed missing types/relations"
    return data


async def seed_workspace(
    session: AsyncSession,
    workspace_id: str,
    *,
    path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Upsert all system types and relations into the given workspace.

    Returns a dict {type_slug: id, relation_slug: id} for downstream seeding.
    """
    data = load_seed(path)

    type_ids: dict[str, str] = {}
    for type_def in _topo_sorted_types(data["types"]):
        row_id = await _upsert_type(session, workspace_id, type_def, type_ids)
        type_ids[type_def["slug"]] = row_id

    relation_ids: dict[str, str] = {}
    for rel_def in data["relations"]:
        row_id = await _upsert_relation(session, workspace_id, rel_def, type_ids, relation_ids)
        relation_ids[rel_def["slug"]] = row_id

    # Second pass: resolve inverse_of references that may have been forward-declared.
    for rel_def in data["relations"]:
        inv = rel_def.get("inverse_of")
        if inv and inv in relation_ids:
            await session.execute(
                text(
                    "UPDATE relation_type SET inverse_of_id = :inv "
                    "WHERE id = :rid AND (inverse_of_id IS DISTINCT FROM :inv)"
                ),
                {"inv": relation_ids[inv], "rid": relation_ids[rel_def["slug"]]},
            )

    log.info(
        "ontology.seed.completed",
        workspace_id=workspace_id,
        types=len(type_ids),
        relations=len(relation_ids),
    )
    return {"types": type_ids, "relations": relation_ids}


def _topo_sorted_types(types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_slug = {t["slug"]: t for t in types}
    visited: set[str] = set()
    out: list[dict[str, Any]] = []

    def visit(slug: str) -> None:
        if slug in visited:
            return
        node = by_slug[slug]
        parent = node.get("extends")
        if parent and parent in by_slug:
            visit(parent)
        visited.add(slug)
        out.append(node)

    for t in types:
        visit(t["slug"])
    return out


async def _upsert_type(
    session: AsyncSession,
    workspace_id: str,
    type_def: dict[str, Any],
    type_ids: dict[str, str],
) -> str:
    slug = type_def["slug"]
    parent = type_def.get("extends")
    extends_id = type_ids.get(parent) if parent else None

    result = await session.execute(
        text(
            """
            INSERT INTO entity_type
              (workspace_id, name, slug, extends_id, schema, ui_hints, description, system)
            VALUES
              (:workspace_id, :name, :slug, :extends_id,
               CAST(:schema AS jsonb), CAST(:ui_hints AS jsonb),
               :description, :system)
            ON CONFLICT (workspace_id, slug) DO UPDATE SET
              name = EXCLUDED.name,
              extends_id = EXCLUDED.extends_id,
              schema = EXCLUDED.schema,
              ui_hints = EXCLUDED.ui_hints,
              description = EXCLUDED.description,
              system = EXCLUDED.system
            RETURNING id::text
            """
        ),
        {
            "workspace_id": workspace_id,
            "name": type_def["name"],
            "slug": slug,
            "extends_id": extends_id,
            "schema": _as_json(type_def.get("schema") or {"type": "object", "properties": {}, "additionalProperties": True}),
            "ui_hints": _as_json(type_def.get("ui_hints", {})),
            "description": type_def.get("description"),
            "system": bool(type_def.get("system", False)),
        },
    )
    return result.scalar_one()


async def _upsert_relation(
    session: AsyncSession,
    workspace_id: str,
    rel_def: dict[str, Any],
    type_ids: dict[str, str],
    relation_ids: dict[str, str],
) -> str:
    slug = rel_def["slug"]

    result = await session.execute(
        text(
            """
            INSERT INTO relation_type
              (workspace_id, name, slug, description,
               domain_type_id, range_type_id,
               cardinality_subject, cardinality_object,
               "symmetric", transitive, temporal, high_stakes,
               ui_hints, system)
            VALUES
              (:workspace_id, :name, :slug, :description,
               :domain_type_id, :range_type_id,
               :card_subj, :card_obj,
               :symmetric, :transitive, :temporal, :high_stakes,
               CAST(:ui_hints AS jsonb), :system)
            ON CONFLICT (workspace_id, slug) DO UPDATE SET
              name = EXCLUDED.name,
              description = EXCLUDED.description,
              domain_type_id = EXCLUDED.domain_type_id,
              range_type_id = EXCLUDED.range_type_id,
              cardinality_subject = EXCLUDED.cardinality_subject,
              cardinality_object = EXCLUDED.cardinality_object,
              "symmetric" = EXCLUDED."symmetric",
              transitive = EXCLUDED.transitive,
              temporal = EXCLUDED.temporal,
              high_stakes = EXCLUDED.high_stakes,
              ui_hints = EXCLUDED.ui_hints,
              system = EXCLUDED.system
            RETURNING id::text
            """
        ),
        {
            "workspace_id": workspace_id,
            "name": rel_def["name"],
            "slug": slug,
            "description": rel_def.get("description"),
            "domain_type_id": type_ids.get(rel_def.get("domain") or ""),
            "range_type_id": type_ids.get(rel_def.get("range") or ""),
            "card_subj": rel_def.get("cardinality_subject", "many"),
            "card_obj": rel_def.get("cardinality_object", "many"),
            "symmetric": bool(rel_def.get("symmetric", False)),
            "transitive": bool(rel_def.get("transitive", False)),
            "temporal": bool(rel_def.get("temporal", True)),
            "high_stakes": bool(rel_def.get("high_stakes", False)),
            "ui_hints": _as_json(rel_def.get("ui_hints", {})),
            "system": bool(rel_def.get("system", False)),
        },
    )
    return result.scalar_one()


def _as_json(value: Any) -> str:
    import json

    return json.dumps(value)
