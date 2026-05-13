"""Entity-resolution cascade — tiers 1/2/3 and cluster safeguards."""
from __future__ import annotations

import pytest

from app.db.session import session_scope
from app.domain import entity_resolver as resolver_mod


@pytest.mark.asyncio
async def test_tier1_external_ref_short_circuits(two_people):
    """Exact-match on entity_external_ref returns immediately, score 1.0."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await resolver_mod.add_external_ref(
            session,
            workspace_id=ws_id,
            entity_id=two_people["alice"],
            kind="email",
            value="alice@example.com",
        )

        resolution = await resolver_mod.resolve(
            session,
            workspace_id=ws_id,
            candidate=resolver_mod.EntityCandidate(
                canonical="Alice Smith",  # doesn't match canonical
                type_slug="person",
                external_refs=[
                    resolver_mod.ExternalRef(kind="email", value="alice@example.com"),
                ],
            ),
            enable_llm=False,
        )

    assert resolution.tier == "rules"
    assert resolution.decision == "match"
    assert resolution.entity_id == two_people["alice"]
    assert resolution.score == 1.0


@pytest.mark.asyncio
async def test_tier1_canonical_exact_match(two_people):
    """Citext-style canonical equality short-circuits, even without external ref."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        resolution = await resolver_mod.resolve(
            session,
            workspace_id=ws_id,
            candidate=resolver_mod.EntityCandidate(
                canonical="alice",  # canonical is "Alice" — case-insensitive
                type_slug="person",
            ),
            enable_llm=False,
        )

    assert resolution.tier == "rules"
    assert resolution.decision == "match"
    assert resolution.entity_id == two_people["alice"]


@pytest.mark.asyncio
async def test_tier2_no_match_when_far(two_people):
    """A name with no trigram overlap returns no_match without firing the LLM."""
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        resolution = await resolver_mod.resolve(
            session,
            workspace_id=ws_id,
            candidate=resolver_mod.EntityCandidate(
                canonical="Zephyr Quokka",
                type_slug="person",
            ),
            enable_llm=False,
        )
    assert resolution.decision == "no_match"
    assert resolution.entity_id is None


@pytest.mark.asyncio
async def test_cluster_safeguard_small_clusters_pass(workspace):
    ws_id = workspace["workspace_id"]
    user_id = workspace["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        ok, reason = await resolver_mod.cluster_is_safe_to_merge(
            session, workspace_id=ws_id, entity_ids=["a", "b", "c"]
        )
    assert ok
    assert reason is None


@pytest.mark.asyncio
async def test_external_ref_listing_roundtrips(two_people):
    ws_id = two_people["workspace_id"]
    user_id = two_people["user_id"]
    async with session_scope(workspace_id=ws_id, user_id=user_id) as session:
        await resolver_mod.add_external_ref(
            session,
            workspace_id=ws_id,
            entity_id=two_people["alice"],
            kind="email",
            value="alice@example.com",
            source_ref="drive:msg/123",
        )
        await resolver_mod.add_external_ref(
            session,
            workspace_id=ws_id,
            entity_id=two_people["alice"],
            kind="slug",
            value="alice-smith",
        )
        refs = await resolver_mod.list_external_refs(
            session, entity_id=two_people["alice"]
        )
    kinds = sorted(r["kind"] for r in refs)
    assert kinds == ["email", "slug"]
