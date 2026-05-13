"""Knowledge-worker scenarios — Drive/Notion ingest → search → entity
timeline → review queue → export.

Each test exercises a real end-to-end flow that a knowledge worker at
the first enterprise customer would run. Tests hit a real Postgres and
the in-process MinIO/Redis. The Drive + Notion connectors are pinned to
mock mode by the ``enterprise_workspace`` fixture.

All tests share the ``enterprise_workspace`` fixture from
``tests/fixtures/enterprise.py``. The fixture seeds 3 users with bridged
Google identities matching the Drive mock's ACL principals, a default
``pii``/``public`` mutually_exclusive policy, and registered Drive +
Notion connector_instances in mock mode.
"""
from __future__ import annotations

import gzip
import io
import os
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text

from app.auth.jwt import Principal
from app.connectors import _drive_mock, _notion_mock
from app.connectors.upsert import upsert_item
from app.db.session import session_scope
from app.domain import edge as edge_mod
from app.domain import entity as entity_mod
from app.domain import episode as episode_mod
from app.domain import proposals as proposals_mod
from app.domain import provenance as prov_mod
from app.domain import sensitivity as sens_mod
from app.retrieval.hybrid import search as hybrid_search
from tests.fixtures.enterprise import EnterpriseFixture


pytestmark = pytest.mark.scenario


def _principal(user: Any, workspace_id: str) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        workspace_id=workspace_id,
        role=user.role,
        claims={},
        kind="user",
    )


async def _ingest_drive_mock(
    enterprise: EnterpriseFixture,
) -> None:
    """Run the Drive mock's initial crawl directly through ``upsert_item``.

    Bypasses the OAuth/credentials machinery (covered by test_drive_e2e)
    so scenario tests focus on the post-ingest behaviour.
    """
    ws_id = enterprise.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=enterprise.owner.id) as session:
        for item in _drive_mock.initial_items():
            await upsert_item(
                session,
                workspace_id=ws_id,
                connector_instance_id=enterprise.drive_instance_id,
                item=item,
            )


# ---------------------------------------------------------------------------
# K1. Drive ingest → search → ACL filter (per-user visibility matrix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drive_ingest_and_acl_visibility(enterprise_workspace):
    e = enterprise_workspace
    await _ingest_drive_mock(e)

    ws_id = e.workspace_id

    # Sanity check: ingest landed the three mock episodes.
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        ingested = (
            await session.execute(
                text(
                    "SELECT external_id FROM episode "
                    "WHERE connector_instance_id = CAST(:id AS uuid)"
                ),
                {"id": e.drive_instance_id},
            )
        ).scalars().all()
    assert set(ingested) == {"alpha-shared", "bravo-team", "charlie-private"}

    # Alice (alice@acme.com) — domain match against alpha-shared,
    # explicit ACL on bravo-team. Search hits use ``source_kind`` as
    # the title field; assert visibility via the snippet content
    # ("Q3 OKRs" appears in alpha-shared's content_text).
    alice_principal = _principal(e.alice, ws_id)
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        hits = await hybrid_search(
            session,
            workspace_id=ws_id,
            query="engineering",
            limit=20,
            include_kinds=("episode",),
            principal=alice_principal,
        )
    alice_snippets = " ".join(h.snippet for h in hits)
    assert "engineering OKRs" in alice_snippets, alice_snippets

    # Charlie-private is hr@-only. Alice must NOT see it.
    alice_ids = {h.id for h in hits}
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        charlie_id = (
            await session.execute(
                text(
                    "SELECT id::text FROM episode "
                    "WHERE external_id = 'charlie-private' "
                    "AND deleted_at IS NULL"
                )
            )
        ).scalar_one()
    assert charlie_id not in alice_ids


# ---------------------------------------------------------------------------
# K2. Bi-temporal as-of query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bi_temporal_as_of(enterprise_workspace):
    """Two facts overlapping in time → cardinality-one closure fires →
    as_of_query at different timestamps returns the right one."""
    e = enterprise_workspace
    ws_id = e.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice K2", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Acme K2", embed=False,
        )
        globex = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Globex K2", embed=False,
        )

        # Alice → Acme since Jan 2024.
        await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=acme.id,
            fact="Alice works at Acme K2",
            valid_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            embed=False,
            run_contradictor=False,
        )
        # Alice → Globex since June 2025 — closure should fire on Acme.
        await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=globex.id,
            fact="Alice works at Globex K2",
            valid_from=datetime(2025, 6, 1, tzinfo=timezone.utc),
            embed=False,
            run_contradictor=False,
        )

        # as-of in 2024 → Acme.
        rows_2024 = await edge_mod.as_of(
            session,
            valid_at=datetime(2024, 9, 1, tzinfo=timezone.utc),
            subject_id=alice.id,
            predicate="works_at",
        )
        # as-of in 2025 → Globex.
        rows_2025 = await edge_mod.as_of(
            session,
            valid_at=datetime(2025, 9, 1, tzinfo=timezone.utc),
            subject_id=alice.id,
            predicate="works_at",
        )

    assert any(r.object_id == acme.id for r in rows_2024)
    assert any(r.object_id == globex.id for r in rows_2025)


# ---------------------------------------------------------------------------
# K3. Entity timeline + provenance pill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_history_carries_provenance(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice K3", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Acme K3", embed=False,
        )
        activity_id = await prov_mod.start_activity(
            session,
            workspace_id=ws_id,
            kind="manual_edit",
            agent_kind="user",
            agent_ref=e.alice.id,
        )
        edge = await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=acme.id,
            fact="Alice K3 works at Acme K3",
            embed=False,
            run_contradictor=False,
            prov_activity_id=activity_id,
        )
        await prov_mod.end_activity(session, activity_id)

        doc = await prov_mod.get_edge_provenance(session, edge.id)

    assert doc is not None
    assert doc["wasGeneratedBy"]["dce:kind"] == "manual_edit"
    assert (
        doc["wasGeneratedBy"]["wasAssociatedWith"]["dce:agentKind"]
        == "user"
    )


# ---------------------------------------------------------------------------
# K4. Low-confidence extraction → review → approve → search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_confidence_review_approve_search(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice K4", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Acme K4", embed=False,
        )
        ep = await episode_mod.add_episode(
            session,
            workspace_id=ws_id,
            content="Alice K4 joined Acme K4.",
            source_kind="agent",
            embed=False,
        )

        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=acme.id,
            fact="Alice K4 works at Acme K4",
            confidence=0.5,
            source_id=ep.id,
            source_kind="episode",
            created_by=e.alice.id,
        )
        assert write.kind == "pending"

        pending = await proposals_mod.list_proposals(
            session, workspace_id=ws_id, status="pending"
        )
        assert any(p.id == write.pending_fact_id for p in pending)

        approved = await proposals_mod.approve_proposal(
            session,
            proposal_id=write.pending_fact_id,
            principal_user_id=e.alice.id,
        )
        live_edges = await edge_mod.live_edges(
            session, subject_id=alice.id, predicate="works_at",
        )
    assert any(le.id == approved.id for le in live_edges)


# ---------------------------------------------------------------------------
# K5. High-stakes contradiction routed to pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_stakes_contradiction_goes_to_pending(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        # `works_at` is high_stakes + cardinality_object=one in seed.
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice K5", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Acme K5", embed=False,
        )
        globex = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Globex K5", embed=False,
        )

        await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=acme.id,
            fact="Alice K5 works at Acme K5",
            embed=False,
            run_contradictor=False,
        )
        # Same subject, same predicate, different object — propose_fact
        # should route to pending with high_stakes_contradiction.
        write = await edge_mod.propose_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=globex.id,
            fact="Alice K5 works at Globex K5",
            confidence=0.95,
            created_by=e.alice.id,
        )
        proposal = await proposals_mod.get_proposal(session, write.pending_fact_id)

    assert write.kind == "pending"
    assert proposal is not None
    assert proposal.reason == "high_stakes_contradiction"


# ---------------------------------------------------------------------------
# K6. Label policy drops for non-admin, bypasses for admin (J3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_label_policy_drops_for_editor_not_admin(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        ep = await episode_mod.add_episode(
            session,
            workspace_id=ws_id,
            content="K6 conflict episode.",
            source_kind="agent",
            embed=False,
        )
        for slug in ("pii", "public"):
            await sens_mod.assign_label(
                session, workspace_id=ws_id, target_kind="episode",
                target_id=ep.id, label_slug=slug,
            )

        candidates = [{"kind": "episode", "id": ep.id}]

        editor_kept, editor_summary = await sens_mod.apply_label_policy(
            session,
            workspace_id=ws_id,
            candidates=[dict(c) for c in candidates],
            principal=_principal(e.alice, ws_id),
        )
        admin_kept, _ = await sens_mod.apply_label_policy(
            session,
            workspace_id=ws_id,
            candidates=[dict(c) for c in candidates],
            principal=_principal(e.admin, ws_id),
        )
    assert editor_kept == []
    assert editor_summary["dropped"] == 1
    assert len(admin_kept) == 1


# ---------------------------------------------------------------------------
# K7. Source-recheck fires when workspace is high-sensitivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_sensitivity_source_recheck_drops_revoked(
    enterprise_workspace, monkeypatch
):
    e = enterprise_workspace
    await _ingest_drive_mock(e)
    ws_id = e.workspace_id

    # Flip the flag.
    async with session_scope(workspace_id=ws_id, user_id=e.owner.id) as session:
        await session.execute(
            text(
                "UPDATE workspace SET high_sensitivity = TRUE WHERE id = :id"
            ),
            {"id": ws_id},
        )

    # Patch the Drive connector so EVERY check_access call returns False.
    from app.connectors import google_drive

    async def deny(self, session, *, workspace_id, principal_user_id, source_ref):
        return False

    monkeypatch.setattr(
        google_drive.GoogleDriveConnector, "check_access", deny, raising=True
    )

    # Carol should now see zero edges (no episodes show through either,
    # but we focus on the edge fan-out from the alpha-shared episode).
    alice_principal = _principal(e.alice, ws_id)
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        # Force at least one edge to exist tied to a Drive episode.
        alice_ent = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice K7", embed=False,
        )
        # Pick the alpha-shared episode.
        ep_id = (
            await session.execute(
                text(
                    "SELECT id::text FROM episode "
                    "WHERE external_id = 'alpha-shared' "
                    "AND deleted_at IS NULL"
                )
            )
        ).scalar_one()
        eng = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Engineering K7", embed=False,
        )
        await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice_ent.id,
            predicate="works_at",
            object_id=eng.id,
            fact="Alice K7 works at Engineering K7",
            source_id=ep_id,
            source_kind="episode",
            embed=False,
            run_contradictor=False,
        )

        # Hybrid search returns nothing for edges because source-recheck
        # denied every backing episode. (No need for embeddings — the
        # text/FTS path still produces candidates that then get filtered.)
        hits = await hybrid_search(
            session,
            workspace_id=ws_id,
            query="Engineering",
            limit=10,
            include_kinds=("edge",),
            principal=alice_principal,
        )
    edge_hits_from_alpha = [h for h in hits if h.kind == "edge"]
    # Source recheck dropped them all.
    assert edge_hits_from_alpha == []


# ---------------------------------------------------------------------------
# K8. Document revision restore round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_revision_restore_round_trip(enterprise_workspace):
    e = enterprise_workspace
    ws_id = e.workspace_id
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        from app.domain import document as doc_mod

        # Create a doc with 3 blocks via the standard create + block PUT.
        doc = await doc_mod.create_document(
            session,
            workspace_id=ws_id,
            title="Plan K8",
            type_slug="document",
            created_by=e.alice.id,
        )
        original_blocks = [
            {
                "id": f"00000000-0000-0000-0000-00000000000{i}",
                "parent_block_id": None,
                "position": i,
                "block_type": "paragraph",
                "content": {"text": f"Block {i}"},
                "props": {},
                "search_text": f"Block {i}",
            }
            for i in range(1, 4)
        ]
        await doc_mod.replace_block_tree(
            session, document_id=doc.id, blocks=original_blocks
        )

        rev_id = await doc_mod.snapshot_revision(
            session,
            document_id=doc.id,
            actor_id=e.alice.id,
            note="initial",
        )
        assert rev_id

        # Edit: drop block 3, add block 4.
        edited = original_blocks[:2] + [
            {
                "id": "00000000-0000-0000-0000-000000000004",
                "parent_block_id": None,
                "position": 4,
                "block_type": "paragraph",
                "content": {"text": "Block 4"},
                "props": {},
                "search_text": "Block 4",
            }
        ]
        await doc_mod.replace_block_tree(
            session, document_id=doc.id, blocks=edited
        )

        await doc_mod.restore_revision(
            session,
            document_id=doc.id,
            revision_id=rev_id,
            actor_id=e.alice.id,
        )
        blocks_after = await doc_mod.list_blocks(session, document_id=doc.id)
        revisions = await doc_mod.list_revisions(session, document_id=doc.id)

    block_ids = sorted(b.id for b in blocks_after)
    assert block_ids == sorted(b["id"] for b in original_blocks)
    # Restore must have captured an auto-snapshot of the edited state.
    assert any(
        r.get("note") and "auto-snapshot" in r["note"] for r in revisions
    )


# ---------------------------------------------------------------------------
# K9. Workspace + user export round-trip via S3 helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_export_round_trip(enterprise_workspace):
    """Run the workspace export job directly and inspect the gzipped
    JSONL it pushes to MinIO."""
    e = enterprise_workspace
    ws_id = e.workspace_id

    # Seed at least one row per dumped table that the fixture didn't
    # already populate. Episode + edge.
    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice K9", embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Acme K9", embed=False,
        )
        await edge_mod.add_fact(
            session,
            workspace_id=ws_id,
            subject_id=alice.id,
            predicate="works_at",
            object_id=acme.id,
            fact="Alice K9 works at Acme K9",
            embed=False,
            run_contradictor=False,
        )
        await episode_mod.add_episode(
            session,
            workspace_id=ws_id,
            content="K9 demo episode.",
            source_kind="agent",
            embed=False,
        )

    # Create the export_job row that the worker expects.
    async with session_scope(workspace_id=ws_id, user_id=e.owner.id) as session:
        job_row = (
            await session.execute(
                text(
                    """
                    INSERT INTO export_job
                      (workspace_id, requester_user_id, scope, status)
                    VALUES (CAST(:w AS uuid), CAST(:u AS uuid),
                            'workspace', 'queued')
                    RETURNING id::text
                    """
                ),
                {"w": ws_id, "u": e.owner.id},
            )
        ).first()
        job_id = job_row[0]

    # MinIO requires CONNECTOR_SECRET_KEY too in some paths — set a
    # reasonable test key for the storage client.
    os.environ.setdefault("CONNECTOR_SECRET_KEY", "test-key")

    from app.workers.export import run_workspace_export

    result = await run_workspace_export(
        {"job_id": job_id}, job_id=job_id, workspace_id=ws_id
    )
    assert result["status"] == "completed", result

    # Read the artifact back out of MinIO and confirm shape.
    from app.core.storage import get_client

    async with session_scope(workspace_id=ws_id, user_id=e.owner.id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_key, byte_size FROM export_job "
                    "WHERE id = :id"
                ),
                {"id": job_id},
            )
        ).first()
    key = row[0]
    assert key

    from app.core.config import get_settings

    bucket = get_settings().s3_bucket
    obj = get_client().get_object(bucket, key)
    raw = obj.read()
    obj.close()
    obj.release_conn()
    decoded = gzip.decompress(raw).decode("utf-8")
    tables = set()
    for line in decoded.splitlines():
        if not line.strip():
            continue
        import json as _json
        rec = _json.loads(line)
        tables.add(rec.get("_table"))

    for required in ("entity", "edge", "episode", "sensitivity_label", "action_type"):
        assert required in tables, f"export missing rows for {required}"
