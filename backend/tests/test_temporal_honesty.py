"""Temporal honesty in the extraction pipeline (Phase QQ1).

When the LLM doesn't emit an explicit ``valid_from`` on an extracted
edge, the pipeline now defaults to the source episode's
``occurred_at`` — not the ingestion instant. Critical for onboarding
agents that mine historical documents.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain.workspace import create_workspace


async def _setup() -> tuple[str, str, str, str]:
    owner_id = str(uuid4())
    suffix = uuid4().hex[:8]
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, email, password_hash, name) "
                "VALUES (CAST(:id AS uuid), :e, 'x', 'qq1')"
            ),
            {"id": owner_id, "e": f"qq1-{suffix}@x.com"},
        )
    async with session_scope(user_id=owner_id) as s:
        ws = await create_workspace(
            s, owner_user_id=owner_id, slug=f"qq1-{suffix}",
            name="QQ1",
        )
    ws_id = ws.id
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        alice = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="person",
            canonical="Alice T", embed=False,
        )
        acme = await entity_mod.create(
            s, workspace_id=ws_id, type_ref="organization",
            canonical="Acme T", embed=False,
        )
    return owner_id, ws_id, alice.id, acme.id


@pytest.mark.asyncio
async def test_pipeline_defaults_valid_from_to_episode_occurred_at(monkeypatch):
    """Episode with ``occurred_at = 2019-03-15``; LLM leaves
    ``valid_from`` null. The created edge must land at 2019, not at
    ingestion time."""
    owner_id, ws_id, _alice_id, _acme_id = await _setup()
    historical = datetime(2019, 3, 15, 12, 0, 0, tzinfo=UTC)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Alice joined Acme as a senior engineer.",
            source_kind="agent",
            occurred_at=historical,
            embed=False,
        )

    from app.extraction import pipeline as pipeline_mod
    from app.extraction.pipeline import (
        ExtractedEdge,
        ExtractedEntity,
        Extraction,
    )

    async def fake_run_llm(*, snapshot: Any, text_: str) -> Extraction:
        return Extraction(
            entities=[
                ExtractedEntity(local_id="alice", name="Alice T", type_slug="person"),
                ExtractedEntity(local_id="acme", name="Acme T", type_slug="organization"),
            ],
            edges=[
                ExtractedEdge(
                    subject_local_id="alice",
                    predicate_slug="works_at",
                    object_local_id="acme",
                    fact="Alice works at Acme",
                    valid_from=None,
                )
            ],
        )

    monkeypatch.setattr(pipeline_mod, "_run_llm", fake_run_llm)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        result = await pipeline_mod.process_episode(
            s, episode_id=ep.id, actor_id=owner_id,
        )

    # works_at is high_stakes — extraction routes through propose_fact,
    # which on a fresh slate falls through to add_fact. Either an edge
    # or a pending fact may be produced depending on workspace
    # extraction policy; assert whichever landed carries the 2019 date.
    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        if result.created_edges:
            edge_id = result.created_edges[0]
            row = (
                await s.execute(
                    text(
                        "SELECT lower(valid_time)::text AS vf "
                        "FROM edge WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": edge_id},
                )
            ).mappings().first()
            assert row is not None
            assert row["vf"].startswith("2019-03-15"), row["vf"]
        else:
            assert result.pending_facts, result.errors
            pf_id = result.pending_facts[0]
            row = (
                await s.execute(
                    text(
                        "SELECT valid_from::text AS vf FROM pending_fact "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": pf_id},
                )
            ).mappings().first()
            assert row is not None
            assert row["vf"].startswith("2019-03-15"), row["vf"]


@pytest.mark.asyncio
async def test_explicit_valid_from_overrides_episode_date(monkeypatch):
    """When the LLM did extract a date, it wins over the episode's
    ``occurred_at`` — the document date is the FALLBACK, not the cap."""
    owner_id, ws_id, _alice_id, _acme_id = await _setup()
    doc_date = datetime(2019, 3, 15, 12, 0, 0, tzinfo=UTC)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Alice has worked at Acme since 2015-01-01.",
            source_kind="agent",
            occurred_at=doc_date,
            embed=False,
        )

    from app.extraction import pipeline as pipeline_mod
    from app.extraction.pipeline import (
        ExtractedEdge,
        ExtractedEntity,
        Extraction,
    )

    async def fake_run_llm(*, snapshot: Any, text_: str) -> Extraction:
        return Extraction(
            entities=[
                ExtractedEntity(local_id="alice", name="Alice T", type_slug="person"),
                ExtractedEntity(local_id="acme", name="Acme T", type_slug="organization"),
            ],
            edges=[
                ExtractedEdge(
                    subject_local_id="alice",
                    predicate_slug="works_at",
                    object_local_id="acme",
                    fact="Alice works at Acme since 2015",
                    valid_from="2015-01-01",
                )
            ],
        )

    monkeypatch.setattr(pipeline_mod, "_run_llm", fake_run_llm)

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        result = await pipeline_mod.process_episode(
            s, episode_id=ep.id, actor_id=owner_id,
        )

    async with session_scope(workspace_id=ws_id, user_id=owner_id) as s:
        if result.created_edges:
            row = (
                await s.execute(
                    text(
                        "SELECT lower(valid_time)::text AS vf "
                        "FROM edge WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": result.created_edges[0]},
                )
            ).mappings().first()
            assert row["vf"].startswith("2015-01-01"), row["vf"]
        else:
            assert result.pending_facts, result.errors
            row = (
                await s.execute(
                    text(
                        "SELECT valid_from::text AS vf FROM pending_fact "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": result.pending_facts[0]},
                )
            ).mappings().first()
            assert row["vf"].startswith("2015-01-01"), row["vf"]
