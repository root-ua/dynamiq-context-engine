"""Ontology invariants: schema validation, subtype checking, CRUD."""
from __future__ import annotations

import pytest

from app.db.session import session_scope
from app.domain import ontology as ontology_mod
from app.domain.ontology import OntologyError


@pytest.mark.asyncio
async def test_builtin_ontology_is_seeded(workspace):
    async with session_scope(workspace_id=workspace["workspace_id"]) as session:
        snap = await ontology_mod.snapshot(session)
    slugs = {t.slug for t in snap.types}
    for required in ("thing", "agent", "person", "organization", "note", "task", "meeting"):
        assert required in slugs, f"missing built-in type: {required}"


@pytest.mark.asyncio
async def test_subtype_ids_follows_hierarchy(workspace):
    async with session_scope(workspace_id=workspace["workspace_id"]) as session:
        agents = await ontology_mod.subtype_ids(session, "agent")
        persons = await ontology_mod.subtype_ids(session, "person")
    # Person is a subtype of Agent, so Agent's subtype_ids must be a superset.
    assert set(persons).issubset(set(agents))


@pytest.mark.asyncio
async def test_entity_type_cannot_rename_system(workspace):
    async with session_scope(workspace_id=workspace["workspace_id"]) as session:
        person = await ontology_mod.get_entity_type(session, "person")
        assert person is not None
        with pytest.raises(OntologyError):
            await ontology_mod.update_entity_type(
                session, type_id=person.id, name="NotPerson"
            )


@pytest.mark.asyncio
async def test_create_custom_type_and_delete(workspace):
    async with session_scope(workspace_id=workspace["workspace_id"]) as session:
        custom = await ontology_mod.create_entity_type(
            session, workspace_id=workspace["workspace_id"],
            name="Engineer", slug="engineer", extends="person",
            schema={"type": "object", "properties": {"level": {"type": "string"}}},
        )
        assert custom.hierarchy.startswith("thing.agent.person.")

        # Custom type (not system) can be deleted.
        await ontology_mod.delete_entity_type(session, custom.id)
        again = await ontology_mod.get_entity_type(session, custom.id)
        assert again is None
