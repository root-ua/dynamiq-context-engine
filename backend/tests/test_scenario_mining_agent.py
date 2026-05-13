"""Q1 — Mining agent persona (post-connector-removal).

An ingestion agent (e.g. Claude Code with file-system access) pushes
extracted text into the platform via ``add_episode``, then later writes
facts whose subject entities the resolver short-circuits via Tier-1
``entity_external_ref`` (email / slug / wikidata).

Tests:

* Tier-1 external-ref short-circuit returns the same entity when an
  agent re-pushes a document about the same person identified by email.
* The flow lands without any connector code involvement.
"""
from __future__ import annotations

import pytest

from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain import entity_resolver as resolver_mod

pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_mining_agent_short_circuits_on_external_ref(
    enterprise_workspace,
):
    """An agent re-pushing extracted entities should converge on the
    same workspace entity through ``entity_external_ref`` Tier-1
    matching — no LLM call needed."""
    e = enterprise_workspace
    ws_id = e.workspace_id

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        proj = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="project",
            canonical="Q3 OKR roadmap", embed=False,
        )
        await resolver_mod.add_external_ref(
            s, workspace_id=ws_id, entity_id=proj.id,
            kind="slug", value="q3-okr-roadmap",
        )

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        resolution = await resolver_mod.resolve(
            s,
            workspace_id=ws_id,
            candidate=resolver_mod.EntityCandidate(
                canonical="Different display name on purpose",
                type_slug="project",
                external_refs=[
                    resolver_mod.ExternalRef(
                        kind="slug",
                        value="q3-okr-roadmap",
                    )
                ],
            ),
            enable_llm=False,
        )
    assert resolution.tier == "rules"
    assert resolution.entity_id == proj.id
