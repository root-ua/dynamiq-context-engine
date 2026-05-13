"""Ontology domain service.

Handles entity types and relation types: CRUD, hierarchy resolution via
ltree, JSON-Schema validation for entity props, and domain/range/cardinality
checks for edges.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from slugify import slugify
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OntologyError(Exception):
    """Raised when an ontology constraint is violated."""


@dataclass
class EntityType:
    id: str
    workspace_id: str | None
    name: str
    slug: str
    extends_id: str | None
    hierarchy: str
    schema: dict[str, Any]
    ui_hints: dict[str, Any]
    description: str | None
    system: bool
    created_at: str
    updated_at: str


@dataclass
class RelationType:
    id: str
    workspace_id: str | None
    name: str
    slug: str
    description: str | None
    domain_type_id: str | None
    range_type_id: str | None
    cardinality_subject: Literal["one", "many"]
    cardinality_object: Literal["one", "many"]
    inverse_of_id: str | None
    symmetric: bool
    transitive: bool
    temporal: bool
    high_stakes: bool
    ui_hints: dict[str, Any]
    system: bool


@dataclass
class OntologySnapshot:
    types: list[EntityType] = field(default_factory=list)
    relations: list[RelationType] = field(default_factory=list)

    def type_by_id(self, type_id: str) -> EntityType | None:
        return next((t for t in self.types if t.id == type_id), None)

    def type_by_slug(self, slug: str) -> EntityType | None:
        return next((t for t in self.types if t.slug == slug), None)

    def relation_by_slug(self, slug: str) -> RelationType | None:
        return next((r for r in self.relations if r.slug == slug), None)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

async def snapshot(session: AsyncSession) -> OntologySnapshot:
    types = await list_entity_types(session)
    relations = await list_relation_types(session)
    return OntologySnapshot(types=types, relations=relations)


async def list_entity_types(session: AsyncSession) -> list[EntityType]:
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, name, slug, extends_id::text,
                   hierarchy::text, schema, ui_hints, description, system,
                   created_at::text, updated_at::text
            FROM entity_type
            WHERE deleted_at IS NULL
            ORDER BY hierarchy
            """
        )
    )
    out: list[EntityType] = []
    for row in result.mappings():
        out.append(EntityType(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            slug=row["slug"],
            extends_id=row["extends_id"],
            hierarchy=row["hierarchy"],
            schema=row["schema"],
            ui_hints=row["ui_hints"],
            description=row["description"],
            system=row["system"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        ))
    return out


async def list_relation_types(session: AsyncSession) -> list[RelationType]:
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, name, slug, description,
                   domain_type_id::text, range_type_id::text,
                   cardinality_subject, cardinality_object,
                   inverse_of_id::text,
                   "symmetric", transitive, temporal, high_stakes,
                   ui_hints, system
            FROM relation_type
            WHERE deleted_at IS NULL
            ORDER BY name
            """
        )
    )
    out: list[RelationType] = []
    for row in result.mappings():
        out.append(RelationType(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            slug=row["slug"],
            description=row["description"],
            domain_type_id=row["domain_type_id"],
            range_type_id=row["range_type_id"],
            cardinality_subject=row["cardinality_subject"],
            cardinality_object=row["cardinality_object"],
            inverse_of_id=row["inverse_of_id"],
            symmetric=row["symmetric"],
            transitive=row["transitive"],
            temporal=row["temporal"],
            high_stakes=row["high_stakes"],
            ui_hints=row["ui_hints"],
            system=row["system"],
        ))
    return out


async def get_entity_type(session: AsyncSession, ref: str) -> EntityType | None:
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, name, slug, extends_id::text,
                   hierarchy::text, schema, ui_hints, description, system,
                   created_at::text, updated_at::text
            FROM entity_type
            WHERE (id::text = :ref OR slug = :ref) AND deleted_at IS NULL
            LIMIT 1
            """
        ),
        {"ref": ref},
    )
    row = result.mappings().first()
    if not row:
        return None
    return EntityType(
        id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
        slug=row["slug"], extends_id=row["extends_id"], hierarchy=row["hierarchy"],
        schema=row["schema"], ui_hints=row["ui_hints"], description=row["description"],
        system=row["system"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


async def get_relation_type(session: AsyncSession, ref: str) -> RelationType | None:
    # Prefer the relation belonging to the session's current workspace when
    # set. With multiple workspaces seeding the same system slugs, ordering
    # by "current workspace first" makes the slug lookup deterministic even
    # when the DB user bypasses RLS (tests, superuser tooling).
    result = await session.execute(
        text(
            """
            SELECT id::text, workspace_id::text, name, slug, description,
                   domain_type_id::text, range_type_id::text,
                   cardinality_subject, cardinality_object,
                   inverse_of_id::text,
                   "symmetric", transitive, temporal, high_stakes,
                   ui_hints, system
            FROM relation_type
            WHERE (id::text = :ref OR slug = :ref) AND deleted_at IS NULL
            ORDER BY
              (workspace_id = current_workspace_id()) DESC NULLS LAST,
              created_at
            LIMIT 1
            """
        ),
        {"ref": ref},
    )
    row = result.mappings().first()
    if not row:
        return None
    return RelationType(
        id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
        slug=row["slug"], description=row["description"],
        domain_type_id=row["domain_type_id"], range_type_id=row["range_type_id"],
        cardinality_subject=row["cardinality_subject"],
        cardinality_object=row["cardinality_object"],
        inverse_of_id=row["inverse_of_id"],
        symmetric=row["symmetric"], transitive=row["transitive"],
        temporal=row["temporal"], high_stakes=row["high_stakes"],
        ui_hints=row["ui_hints"], system=row["system"],
    )


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------

async def create_entity_type(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    slug: str | None = None,
    extends: str | None = None,
    schema: dict[str, Any] | None = None,
    ui_hints: dict[str, Any] | None = None,
    description: str | None = None,
    system: bool = False,
) -> EntityType:
    slug_val = slugify(slug or name, separator="_", lowercase=True)
    extends_id: str | None = None
    if extends:
        parent = await get_entity_type(session, extends)
        if not parent:
            raise OntologyError(f"parent type not found: {extends}")
        extends_id = parent.id

    schema_val = schema or {"type": "object", "properties": {}, "additionalProperties": True}
    _validate_schema_is_valid(schema_val)

    result = await session.execute(
        text(
            """
            INSERT INTO entity_type
              (workspace_id, name, slug, extends_id, schema, ui_hints, description, system)
            VALUES
              (:workspace_id, :name, :slug, :extends_id,
               CAST(:schema AS jsonb), CAST(:ui_hints AS jsonb),
               :description, :system)
            RETURNING id::text
            """
        ),
        {
            "workspace_id": workspace_id,
            "name": name,
            "slug": slug_val,
            "extends_id": extends_id,
            "schema": json.dumps(schema_val),
            "ui_hints": json.dumps(ui_hints or {}),
            "description": description,
            "system": system,
        },
    )
    row_id = result.scalar_one()
    fetched = await get_entity_type(session, row_id)
    assert fetched is not None
    return fetched


async def update_entity_type(
    session: AsyncSession,
    *,
    type_id: str,
    name: str | None = None,
    schema: dict[str, Any] | None = None,
    ui_hints: dict[str, Any] | None = None,
    description: str | None = None,
    extends: str | None | Literal["__unset__"] = "__unset__",
) -> EntityType:
    existing = await get_entity_type(session, type_id)
    if not existing:
        raise OntologyError("entity type not found")
    if existing.system and (name is not None or schema is not None):
        # System types' names/schemas are immutable; ui_hints and description are fine.
        if name and name != existing.name:
            raise OntologyError("cannot rename a system entity type")

    updates: dict[str, Any] = {"id": type_id}
    sets: list[str] = []
    if name is not None:
        updates["name"] = name
        sets.append("name = :name")
    if schema is not None:
        _validate_schema_is_valid(schema)
        updates["schema"] = json.dumps(schema)
        sets.append("schema = CAST(:schema AS jsonb)")
    if ui_hints is not None:
        updates["ui_hints"] = json.dumps(ui_hints)
        sets.append("ui_hints = CAST(:ui_hints AS jsonb)")
    if description is not None:
        updates["description"] = description
        sets.append("description = :description")
    if extends != "__unset__":
        if extends is None:
            updates["extends_id"] = None
            sets.append("extends_id = :extends_id")
        else:
            parent = await get_entity_type(session, extends)
            if not parent:
                raise OntologyError(f"parent type not found: {extends}")
            updates["extends_id"] = parent.id
            sets.append("extends_id = :extends_id")

    if not sets:
        return existing

    await session.execute(
        text(f"UPDATE entity_type SET {', '.join(sets)} WHERE id = :id"),
        updates,
    )
    fetched = await get_entity_type(session, type_id)
    assert fetched is not None
    return fetched


async def delete_entity_type(session: AsyncSession, type_id: str) -> None:
    existing = await get_entity_type(session, type_id)
    if not existing:
        return
    if existing.system:
        raise OntologyError("cannot delete a system entity type")
    # Soft delete — entities of this type are NOT migrated; callers must
    # reassign first.
    await session.execute(
        text("UPDATE entity_type SET deleted_at = now() WHERE id = :id"),
        {"id": type_id},
    )


async def create_relation_type(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    slug: str | None = None,
    description: str | None = None,
    domain: str | None = None,
    range_: str | None = None,
    cardinality_subject: Literal["one", "many"] = "many",
    cardinality_object: Literal["one", "many"] = "many",
    inverse_of: str | None = None,
    symmetric: bool = False,
    transitive: bool = False,
    temporal: bool = True,
    high_stakes: bool = False,
    ui_hints: dict[str, Any] | None = None,
    system: bool = False,
) -> RelationType:
    slug_val = slugify(slug or name, separator="_", lowercase=True)

    domain_id = None
    range_id = None
    if domain:
        dt = await get_entity_type(session, domain)
        if not dt:
            raise OntologyError(f"domain type not found: {domain}")
        domain_id = dt.id
    if range_:
        rt = await get_entity_type(session, range_)
        if not rt:
            raise OntologyError(f"range type not found: {range_}")
        range_id = rt.id

    inverse_id = None
    if inverse_of:
        inv = await get_relation_type(session, inverse_of)
        if not inv:
            raise OntologyError(f"inverse relation not found: {inverse_of}")
        inverse_id = inv.id

    result = await session.execute(
        text(
            """
            INSERT INTO relation_type
              (workspace_id, name, slug, description,
               domain_type_id, range_type_id,
               cardinality_subject, cardinality_object,
               inverse_of_id,
               "symmetric", transitive, temporal, high_stakes,
               ui_hints, system)
            VALUES
              (:workspace_id, :name, :slug, :description,
               :domain_id, :range_id,
               :card_s, :card_o,
               :inverse_id,
               :sym, :trans, :temp, :hs,
               CAST(:ui_hints AS jsonb), :system)
            RETURNING id::text
            """
        ),
        {
            "workspace_id": workspace_id,
            "name": name, "slug": slug_val, "description": description,
            "domain_id": domain_id, "range_id": range_id,
            "card_s": cardinality_subject, "card_o": cardinality_object,
            "inverse_id": inverse_id,
            "sym": symmetric, "trans": transitive, "temp": temporal, "hs": high_stakes,
            "ui_hints": json.dumps(ui_hints or {}),
            "system": system,
        },
    )
    row_id = result.scalar_one()
    fetched = await get_relation_type(session, row_id)
    assert fetched is not None
    return fetched


async def update_relation_type(
    session: AsyncSession,
    *,
    relation_id: str,
    **fields: Any,
) -> RelationType:
    existing = await get_relation_type(session, relation_id)
    if not existing:
        raise OntologyError("relation type not found")

    allowed = {
        "name", "description", "cardinality_subject", "cardinality_object",
        "symmetric", "transitive", "temporal", "high_stakes", "ui_hints",
    }
    updates: dict[str, Any] = {"id": relation_id}
    sets: list[str] = []
    for key, value in fields.items():
        if value is None or key not in allowed:
            continue
        if key == "ui_hints":
            updates[key] = json.dumps(value)
            sets.append(f'"{key}" = CAST(:{key} AS jsonb)')
        else:
            updates[key] = value
            sets.append(f'"{key}" = :{key}')

    # Type/IRI changes go through explicit APIs below.
    if fields.get("domain"):
        dt = await get_entity_type(session, fields["domain"])
        if not dt:
            raise OntologyError(f"domain type not found: {fields['domain']}")
        updates["domain_id"] = dt.id
        sets.append("domain_type_id = :domain_id")
    if fields.get("range_"):
        rt = await get_entity_type(session, fields["range_"])
        if not rt:
            raise OntologyError(f"range type not found: {fields['range_']}")
        updates["range_id"] = rt.id
        sets.append("range_type_id = :range_id")

    if not sets:
        return existing

    await session.execute(
        text(f"UPDATE relation_type SET {', '.join(sets)} WHERE id = :id"),
        updates,
    )
    fetched = await get_relation_type(session, relation_id)
    assert fetched is not None
    return fetched


async def delete_relation_type(session: AsyncSession, relation_id: str) -> None:
    existing = await get_relation_type(session, relation_id)
    if not existing:
        return
    if existing.system:
        raise OntologyError("cannot delete a system relation type")
    await session.execute(
        text("UPDATE relation_type SET deleted_at = now() WHERE id = :id"),
        {"id": relation_id},
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_entity_props(entity_type: EntityType, props: dict[str, Any]) -> None:
    schema = entity_type.schema or {"type": "object"}
    try:
        Draft202012Validator(schema).validate(props)
    except JsonSchemaError as exc:
        raise OntologyError(f"entity props do not satisfy {entity_type.slug}: {exc.message}") from exc


async def validate_edge(
    session: AsyncSession,
    *,
    relation: RelationType,
    subject_type_id: str,
    object_type_id: str,
) -> None:
    """Check that subject/object types satisfy the relation's domain/range.

    Uses ltree descendant check so abstract domains (e.g. Agent) accept
    subtypes (Person, Organization).
    """
    if relation.domain_type_id:
        ok = await session.execute(
            text(
                """
                SELECT (child.hierarchy <@ parent.hierarchy)
                FROM entity_type child, entity_type parent
                WHERE child.id = :child_id AND parent.id = :parent_id
                """
            ),
            {"child_id": subject_type_id, "parent_id": relation.domain_type_id},
        )
        if not ok.scalar():
            raise OntologyError(
                f"subject type does not satisfy domain of relation {relation.slug}"
            )

    if relation.range_type_id:
        ok = await session.execute(
            text(
                """
                SELECT (child.hierarchy <@ parent.hierarchy)
                FROM entity_type child, entity_type parent
                WHERE child.id = :child_id AND parent.id = :parent_id
                """
            ),
            {"child_id": object_type_id, "parent_id": relation.range_type_id},
        )
        if not ok.scalar():
            raise OntologyError(
                f"object type does not satisfy range of relation {relation.slug}"
            )


def _validate_schema_is_valid(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise OntologyError(f"invalid JSON Schema: {exc}") from exc


# ---------------------------------------------------------------------------
# Subtype resolution
# ---------------------------------------------------------------------------

async def subtype_ids(session: AsyncSession, type_ref: str) -> list[str]:
    """Return ids of the given type and all its descendants."""
    result = await session.execute(
        text(
            """
            WITH root AS (
              SELECT hierarchy FROM entity_type
              WHERE (id::text = :ref OR slug = :ref) AND deleted_at IS NULL
              LIMIT 1
            )
            SELECT et.id::text AS id
            FROM entity_type et, root
            WHERE et.hierarchy <@ root.hierarchy AND et.deleted_at IS NULL
            """
        ),
        {"ref": type_ref},
    )
    return [row[0] for row in result.all()]
