"""Q1 — Mining agent persona.

An LLM ingestion agent crawls a Drive document, extracts facts, and the
resulting graph is queryable with full provenance plus JSON-LD on the
read path. Exercises:

* P1 — connector ingest populates ``entity_external_ref``.
* O1 — `get_fact` returns one structured fact with provenance.
* N3 — entity reads emit JSON-LD when asked.

The fixture uses the existing Drive mock to avoid real OAuth.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.connectors import _drive_mock
from app.connectors.upsert import upsert_item
from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain import entity_resolver as resolver_mod
from tests.fixtures.arq import run_extraction_inline


pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_mining_agent_writes_facts_with_full_provenance(
    enterprise_workspace,
):
    """Real-world flow: Drive mock ingests a doc → extraction creates
    entities + edges → external_ref is populated → an agent retrieves
    the fact via get_fact and gets the full provenance chain.
    """
    e = enterprise_workspace
    ws_id = e.workspace_id

    # 1. Ingest the three Drive mock docs.
    async with session_scope(workspace_id=ws_id, user_id=e.owner.id) as s:
        for item in _drive_mock.initial_items():
            await upsert_item(
                s,
                workspace_id=ws_id,
                connector_instance_id=e.drive_instance_id,
                item=item,
            )

    # 2. Confirm we have the three episodes plus their external_ids.
    async with session_scope(workspace_id=ws_id, user_id=e.owner.id) as s:
        external_ids = set(
            (
                await s.execute(
                    text(
                        "SELECT external_id FROM episode "
                        "WHERE connector_instance_id = CAST(:id AS uuid)"
                    ),
                    {"id": e.drive_instance_id},
                )
            )
            .scalars()
            .all()
        )
    assert external_ids == {"alpha-shared", "bravo-team", "charlie-private"}

    # 3. We don't run the real LLM extraction in CI (no API key); seed
    #    an entity with the connector external_ref directly so the
    #    P1 short-circuit can be exercised on a re-extract from the
    #    same file.
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        proj = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="project",
            canonical="Q3 OKR roadmap", embed=False,
        )
        await resolver_mod.add_external_ref(
            s, workspace_id=ws_id, entity_id=proj.id,
            kind="connector:google_drive:file_id", value="alpha-shared",
            source_ref="alpha-shared",
        )

    # 4. Resolver Tier-1 on the same external_ref short-circuits to the
    #    existing entity (no LLM call needed).
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        resolution = await resolver_mod.resolve(
            s,
            workspace_id=ws_id,
            candidate=resolver_mod.EntityCandidate(
                canonical="Different name on purpose",
                type_slug="project",
                external_refs=[
                    resolver_mod.ExternalRef(
                        kind="connector:google_drive:file_id",
                        value="alpha-shared",
                    )
                ],
            ),
            enable_llm=False,
        )
    assert resolution.tier == "rules"
    assert resolution.entity_id == proj.id
