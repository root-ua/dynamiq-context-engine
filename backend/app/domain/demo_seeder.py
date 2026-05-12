"""Populate a workspace with the Halcyon Labs demo dataset.

This is the single orchestration module that turns the hand-authored
seeds under `seeds/demo/halcyon/` into real rows in a Dynamiq workspace.
It goes through the same domain layer the REST API uses (entity / edge
/ document / episode create functions) so RLS, IRI generation,
backlink rebuild, and audit semantics all behave identically.

Idempotency: each seeded entity gets a deterministic IRI derived from
its author-defined `key`. Re-running the seeder against the same
workspace matches existing rows by IRI and updates in place rather than
creating duplicates.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Make the repo root importable so `from seeds.demo... import` works.
# The seeds/ directory lives outside the backend/ package, mounted at
# /seeds in the container but at the repo root when running from a
# checkout. We support both.
_SEEDS_CANDIDATES = [
    Path("/"),                             # container: /seeds/demo/halcyon
    Path(__file__).resolve().parents[3],   # repo root: <repo>/seeds/demo/halcyon
]
for candidate in _SEEDS_CANDIDATES:
    if (candidate / "seeds" / "demo" / "halcyon" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        break

from seeds.demo.halcyon import (  # noqa: E402
    AGENT_SESSIONS,
    DOCUMENTS,
    EDGES,
    EPISODES,
    EXTRA_ENTITY_TYPES,
    EXTRA_RELATION_TYPES,
    ORGS,
    PEOPLE,
    PROJECTS,
)
from seeds.demo.halcyon._types import (  # noqa: E402
    DocumentSeed,
    EdgeSeed,
    EntitySeed,
    EpisodeSeed,
)

from app.core.logging import get_logger  # noqa: E402
from app.domain import document as document_mod  # noqa: E402
from app.domain import edge as edge_mod  # noqa: E402
from app.domain import entity as entity_mod  # noqa: E402
from app.domain import episode as episode_mod  # noqa: E402
from app.domain import ontology as ontology_mod  # noqa: E402

log = get_logger(__name__)


@dataclass
class DemoSeedResult:
    entities_created: int
    entities_updated: int
    edges_created: int
    edges_invalidated: int
    documents_created: int
    episodes_created: int
    agent_sessions_created: int
    home_document_id: str | None
    deleted_entity_keys: tuple[str, ...]
    merged_entity_keys: tuple[str, ...]


# ---------------------------------------------------------------------------
# IRI helpers — how we key entities for idempotency.
# ---------------------------------------------------------------------------

def _demo_iri(workspace_id: str, key: str) -> str:
    """Build a stable IRI for a seed entity.

    The IRI embeds the workspace + the author-defined key. Re-running the
    seeder against the same workspace produces the same IRI, which gives
    us the dedupe handle.
    """
    h = hashlib.sha256(f"{workspace_id}:{key}".encode()).hexdigest()[:12]
    return f"demo:halcyon:{key}:{h}"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

async def seed_demo_workspace(
    session: AsyncSession,
    *,
    workspace_id: str,
    actor_user_id: str,
) -> DemoSeedResult:
    """Populate `workspace_id` with the Halcyon Labs dataset."""

    log.info("demo_seed.start", workspace_id=workspace_id)

    # Phase 0: ontology additions (idempotent by slug).
    await _seed_ontology(session, workspace_id=workspace_id)

    # Phase 1: entities (people, orgs, projects) → map of key → uuid.
    key_to_id: dict[str, str] = {}
    created = 0
    updated = 0
    for ent in (*PEOPLE, *ORGS, *PROJECTS):
        entity_id, was_created = await _upsert_entity(
            session,
            workspace_id=workspace_id,
            ent=ent,
            actor_user_id=actor_user_id,
        )
        key_to_id[ent.key] = entity_id
        created += 1 if was_created else 0
        updated += 0 if was_created else 1

    # Phase 2: documents (create entity-row + document-row, then blocks).
    # Docs are referenceable from edges via source_ref_key, so we need
    # their UUIDs available before inserting edges.
    doc_results: dict[str, str] = {}  # doc key → document_id
    for doc in DOCUMENTS:
        doc_id = await _upsert_document(
            session,
            workspace_id=workspace_id,
            doc=doc,
            key_to_id=key_to_id,
            actor_user_id=actor_user_id,
        )
        doc_results[doc.key] = doc_id

    # Phase 3: episodes. Content stays at "pending" so the user can
    # kick reprocess and watch the real pipeline run.
    episode_results: dict[str, str] = {}
    for ep in EPISODES:
        ep_id = await _upsert_episode(
            session,
            workspace_id=workspace_id,
            ep=ep,
            actor_user_id=actor_user_id,
        )
        episode_results[ep.key] = ep_id

    # Phase 4: edges. Resolve subject/object/source refs from our maps.
    edges_created = 0
    edges_invalidated = 0
    for e in EDGES:
        edge_id, was_invalidated = await _insert_edge(
            session,
            workspace_id=workspace_id,
            e=e,
            key_to_id=key_to_id,
            doc_results=doc_results,
            episode_results=episode_results,
            actor_user_id=actor_user_id,
        )
        if edge_id is not None:
            edges_created += 1
            if was_invalidated:
                edges_invalidated += 1

    # Phase 5: agent sessions + tool calls (direct insert into audit tables).
    sessions_created = 0
    for s in AGENT_SESSIONS:
        if await _upsert_agent_session(
            session,
            workspace_id=workspace_id,
            s=s,
            actor_user_id=actor_user_id,
            key_to_id=key_to_id,
        ):
            sessions_created += 1

    # Phase 6: edge cases.
    # 6a. Merge the Dynamiq duplicate into the canonical.
    merged_keys: tuple[str, ...] = ()
    if "org.dynamiq_duplicate" in key_to_id and "org.dynamiq_canonical" in key_to_id:
        await entity_mod.merge_entities(
            session,
            survivor_id=key_to_id["org.dynamiq_canonical"],
            loser_id=key_to_id["org.dynamiq_duplicate"],
        )
        merged_keys = ("org.dynamiq_duplicate -> org.dynamiq_canonical",)

    # 6b. Soft-delete the deprecated project.
    deleted_keys: tuple[str, ...] = ()
    if "project.lumen_deprecated" in key_to_id:
        await entity_mod.soft_delete(
            session, entity_id=key_to_id["project.lumen_deprecated"]
        )
        deleted_keys = ("project.lumen_deprecated",)

    # Pick the strategy memo as the home document — nicest first-impression
    # landing page when the seeder is called from the onboarding flow.
    home_doc_id = doc_results.get("doc.strategy_memo_2026")

    result = DemoSeedResult(
        entities_created=created,
        entities_updated=updated,
        edges_created=edges_created,
        edges_invalidated=edges_invalidated,
        documents_created=len(doc_results),
        episodes_created=len(episode_results),
        agent_sessions_created=sessions_created,
        home_document_id=home_doc_id,
        deleted_entity_keys=deleted_keys,
        merged_entity_keys=merged_keys,
    )
    log.info("demo_seed.done", **{
        "workspace_id": workspace_id,
        "entities_created": result.entities_created,
        "entities_updated": result.entities_updated,
        "edges_created": result.edges_created,
        "documents": result.documents_created,
        "episodes": result.episodes_created,
        "agent_sessions": result.agent_sessions_created,
    })
    return result


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------

async def _seed_ontology(
    session: AsyncSession, *, workspace_id: str
) -> None:
    for t in EXTRA_ENTITY_TYPES:
        existing = await ontology_mod.get_entity_type(session, t.slug)
        if existing:
            continue
        await ontology_mod.create_entity_type(
            session,
            workspace_id=workspace_id,
            name=t.name,
            slug=t.slug,
            extends=t.extends,
            schema=t.schema,
            ui_hints=t.ui_hints,
            description=t.description,
            system=False,
        )
    for r in EXTRA_RELATION_TYPES:
        existing = await ontology_mod.get_relation_type(session, r.slug)
        if existing:
            continue
        await ontology_mod.create_relation_type(
            session,
            workspace_id=workspace_id,
            name=r.name,
            slug=r.slug,
            description=r.description,
            domain=r.domain,
            range_=r.range_,
            cardinality_subject=r.cardinality_subject,  # type: ignore[arg-type]
            cardinality_object=r.cardinality_object,  # type: ignore[arg-type]
            temporal=r.temporal,
            system=False,
        )


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

async def _upsert_entity(
    session: AsyncSession,
    *,
    workspace_id: str,
    ent: EntitySeed,
    actor_user_id: str,
) -> tuple[str, bool]:
    """Return (entity_id, was_newly_created)."""
    iri = _demo_iri(workspace_id, ent.key)

    # Look up existing by IRI (scoped to workspace via RLS).
    result = await session.execute(
        text("SELECT id::text FROM entity WHERE iri = :iri"),
        {"iri": iri},
    )
    existing = result.first()
    if existing:
        entity_id = existing[0]
        # Update canonical / aliases / props / summary in place. Aliases
        # get rewritten wholesale; that's fine for demo data.
        await session.execute(
            text(
                """
                UPDATE entity
                SET canonical = :canonical,
                    aliases = :aliases,
                    summary = :summary,
                    props = CAST(:props AS jsonb)
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": entity_id,
                "canonical": ent.canonical,
                "aliases": list(ent.aliases),
                "summary": ent.summary,
                "props": json.dumps(ent.props),
            },
        )
        return entity_id, False

    # Create fresh via the normal service path — but override the
    # auto-generated IRI with our deterministic one afterwards.
    created = await entity_mod.create(
        session,
        workspace_id=workspace_id,
        type_ref=ent.type_slug,
        canonical=ent.canonical,
        aliases=list(ent.aliases),
        summary=ent.summary,
        props=ent.props,
        created_by=actor_user_id,
        embed=False,  # no LLM at seed time
    )
    await session.execute(
        text("UPDATE entity SET iri = :iri WHERE id = CAST(:id AS uuid)"),
        {"iri": iri, "id": created.id},
    )
    return created.id, True


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

async def _upsert_document(
    session: AsyncSession,
    *,
    workspace_id: str,
    doc: DocumentSeed,
    key_to_id: dict[str, str],
    actor_user_id: str,
) -> str:
    """Create or update the document-backed entity + block tree.

    The document's backing entity uses the same `doc.<key>` IRI scheme.
    """
    iri = _demo_iri(workspace_id, doc.key)
    # `created_by` is an app_user reference — it points at the person who
    # ran the seed (actor_user_id), not at the demo-dataset "author" (who
    # is a Person entity in the graph). The Person ↔ Document authorship
    # relationship lives in relationships.py as an `authored` edge.
    _ = key_to_id  # reserved for future authorship wiring
    _ = doc.author_key

    result = await session.execute(
        text(
            """
            SELECT d.id::text AS doc_id, d.entity_id::text AS ent_id
            FROM document d JOIN entity e ON e.id = d.entity_id
            WHERE e.iri = :iri
            """
        ),
        {"iri": iri},
    )
    existing = result.mappings().first()
    if existing:
        document_id = existing["doc_id"]
        # Update title on the backing entity.
        await session.execute(
            text(
                "UPDATE entity SET canonical = :title "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"title": doc.title, "id": existing["ent_id"]},
        )
    else:
        created_doc = await document_mod.create_document(
            session,
            workspace_id=workspace_id,
            title=doc.title,
            type_slug=doc.type_slug,
            created_by=actor_user_id,
        )
        document_id = created_doc.id
        await session.execute(
            text("UPDATE entity SET iri = :iri WHERE id = CAST(:id AS uuid)"),
            {"iri": iri, "id": created_doc.entity_id},
        )

    # Resolve entity-mention keys → UUIDs inside the block tree.
    resolved_blocks = _resolve_mentions(doc.blocks, key_to_id)
    await document_mod.replace_block_tree(
        session, document_id=document_id, blocks=list(resolved_blocks)
    )
    # Generate Yjs binary state so the BlockNote editor renders content
    # on first open. Best-effort: if the collab service isn't reachable
    # or HYDRATE_SECRET is unset, we log a warning and leave yjs_state
    # alone — the block tree is still populated.
    await _write_yjs_state(
        session,
        document_id=document_id,
        blocks=list(resolved_blocks),
    )
    return document_id


async def _write_yjs_state(
    session: AsyncSession,
    *,
    document_id: str,
    blocks: list[dict[str, Any]],
) -> None:
    """POST blocks to the collab /internal/hydrate-yjs endpoint and write
    the returned Yjs binary update into document.yjs_state.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.hydrate_secret:
        log.warning(
            "demo_seed.hydrate.skipped",
            reason="HYDRATE_SECRET unset",
            document_id=document_id,
        )
        return

    # Translate our stored block shape (uuid id, block_type, content,
    # props) → BlockNote's wire shape (id, type, content, props, children).
    # The inline node shapes already match — the helpers in
    # seeds/demo/halcyon/_block_helpers.py emit BlockNote-compatible
    # content arrays.
    bn_blocks: list[dict[str, Any]] = []
    for b in blocks:
        if b.get("parent_block_id"):
            # Flattened child blocks are re-nested at projection read
            # time; for seed-time hydration we stay top-level-only,
            # which matches our authored dataset (no nested blocks).
            continue
        bn_blocks.append(
            {
                "id": b["id"],
                "type": b.get("block_type", "paragraph"),
                "content": b.get("content") or [],
                "props": b.get("props") or {},
                "children": [],
            }
        )

    import httpx

    url = f"{settings.collab_internal_url.rstrip('/')}/internal/hydrate-yjs"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                headers={
                    "X-Internal-Auth": settings.hydrate_secret,
                    "Content-Type": "application/json",
                },
                json={"blocks": bn_blocks},
            )
            if resp.status_code != 200:
                log.warning(
                    "demo_seed.hydrate.http_error",
                    document_id=document_id,
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                return
            yjs_bytes = resp.content
    except Exception as exc:
        log.warning(
            "demo_seed.hydrate.request_failed",
            document_id=document_id,
            error=str(exc),
        )
        return

    await session.execute(
        text(
            "UPDATE document SET yjs_state = :state, updated_at = now() "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"state": yjs_bytes, "id": document_id},
    )


def _resolve_mentions(
    blocks: tuple[dict[str, Any], ...],
    key_to_id: dict[str, str],
) -> tuple[dict[str, Any], ...]:
    """Walk each block's content tree and swap `entityMention.props.entityId`
    placeholder keys for the real UUID. Mentions whose key doesn't resolve
    get stripped (better than leaving a broken link in the editor).
    """

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            if node.get("type") == "entityMention":
                props = dict(node.get("props") or {})
                k = props.get("entityId")
                if isinstance(k, str) and k in key_to_id:
                    props["entityId"] = key_to_id[k]
                    return {**node, "props": props}
                # Fallback: render as text so the document still reads.
                label = props.get("label") or k or "(missing entity)"
                return {"type": "text", "text": str(label), "styles": {}}
            out = {
                k: [fix(c) for c in v] if isinstance(v, list) else v
                for k, v in node.items()
            }
            return out
        if isinstance(node, list):
            return [fix(c) for c in node]
        return node

    fixed: list[dict[str, Any]] = []
    for b in blocks:
        nb = dict(b)
        if "content" in nb:
            nb["content"] = [fix(c) for c in nb["content"] or []]
        fixed.append(nb)
    return tuple(fixed)


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

async def _upsert_episode(
    session: AsyncSession,
    *,
    workspace_id: str,
    ep: EpisodeSeed,
    actor_user_id: str,
) -> str:
    # Episodes don't have a canonical IRI slot; we dedupe by source_ref.
    result = await session.execute(
        text(
            "SELECT id::text FROM episode WHERE source_ref = :ref "
            "AND workspace_id = CAST(:ws AS uuid)"
        ),
        {"ref": ep.source_ref, "ws": workspace_id},
    )
    existing = result.first()
    if existing:
        return existing[0]

    created = await episode_mod.add_episode(
        session,
        workspace_id=workspace_id,
        content=ep.content_text,
        source_kind=ep.source_kind,
        source_ref=ep.source_ref,
        occurred_at=ep.occurred_at,
        created_by=actor_user_id,
        embed=False,
    )
    return created.id


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

async def _insert_edge(
    session: AsyncSession,
    *,
    workspace_id: str,
    e: EdgeSeed,
    key_to_id: dict[str, str],
    doc_results: dict[str, str],
    episode_results: dict[str, str],
    actor_user_id: str,
) -> tuple[str | None, bool]:
    """Insert an edge. Returns (edge_id, was_invalidated)."""

    async def _resolve(key: str) -> str | None:
        # Entities (person/org/project) live in key_to_id directly.
        if key in key_to_id:
            return key_to_id[key]
        # Documents resolve via the backing entity row.
        if key in doc_results:
            r = await session.execute(
                text(
                    "SELECT entity_id::text FROM document "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": doc_results[key]},
            )
            row = r.first()
            return row[0] if row else None
        return None

    subj_id = await _resolve(e.subject_key)
    obj_id = await _resolve(e.object_key)
    if not subj_id or not obj_id:
        log.warning(
            "demo_seed.edge.skip",
            subject_key=e.subject_key,
            object_key=e.object_key,
            reason="key not resolved",
        )
        return None, False

    # source_id → episode UUID if the source_ref_key is an episode
    source_id = None
    if e.source_ref_key:
        if e.source_ref_key in episode_results:
            source_id = episode_results[e.source_ref_key]
        elif e.source_ref_key in doc_results:
            source_id = doc_results[e.source_ref_key]

    edge = await edge_mod.add_fact(
        session,
        workspace_id=workspace_id,
        subject_id=subj_id,
        predicate=e.predicate,
        object_id=obj_id,
        fact=e.fact,
        valid_from=e.valid_from,
        valid_to=e.valid_to,
        source_id=source_id,
        source_kind=e.source_kind,
        confidence=e.confidence,
        created_by=actor_user_id,
        embed=False,
    )

    was_invalidated = False
    if e.invalidate_at:
        await edge_mod.invalidate(
            session,
            edge_id=edge.id,
            invalidated_at=e.invalidate_at,
            reason=e.invalidate_reason,
            actor_kind="system",
            actor_id=actor_user_id,
        )
        was_invalidated = True

    return edge.id, was_invalidated


# ---------------------------------------------------------------------------
# Agent sessions
# ---------------------------------------------------------------------------

async def _upsert_agent_session(
    session: AsyncSession,
    *,
    workspace_id: str,
    s: Any,  # AgentSessionSeed
    actor_user_id: str,
    key_to_id: dict[str, str],
) -> bool:
    # Dedupe by the seed key — store it in a synthetic client tag so we
    # can re-find the row on re-seed.
    tag = f"demo:{s.key}"
    existing = await session.execute(
        text(
            "SELECT id FROM agent_session WHERE workspace_id = CAST(:ws AS uuid) "
            "AND client = :client"
        ),
        {"ws": workspace_id, "client": tag},
    )
    if existing.first():
        return False

    # Insert session.
    r = await session.execute(
        text(
            """
            INSERT INTO agent_session
              (workspace_id, user_id, client, started_at, ended_at)
            VALUES (
              CAST(:ws AS uuid), CAST(:user AS uuid), :client, :started, :ended
            )
            RETURNING id::text
            """
        ),
        {
            "ws": workspace_id,
            "user": actor_user_id,
            "client": tag,
            "started": s.started_at,
            "ended": s.calls[-1].occurred_at if s.calls else s.started_at,
        },
    )
    session_id = r.scalar_one()

    for call in s.calls:
        await session.execute(
            text(
                """
                INSERT INTO agent_tool_call
                  (workspace_id, session_id, tool, input, output,
                   error, latency_ms, created_at)
                VALUES (
                  CAST(:ws AS uuid), CAST(:sid AS uuid), :tool,
                  CAST(:input AS jsonb), CAST(:output AS jsonb),
                  :error, :latency, :created
                )
                """
            ),
            {
                "ws": workspace_id,
                "sid": session_id,
                "tool": call.tool,
                "input": json.dumps(call.arguments),
                "output": json.dumps(_inject_ids(call.result, key_to_id)),
                "error": call.error,
                "latency": call.latency_ms,
                "created": call.occurred_at,
            },
        )
    return True


def _inject_ids(obj: Any, key_to_id: dict[str, str]) -> Any:
    """Walk a tool-call result dict and replace `<placeholder>` with a real
    UUID when the surrounding context supplies a `entity_key`. We keep
    this simple: any string value literally equal to `<placeholder>`
    becomes the first entity id we can find. Good enough for demo data.
    """
    if isinstance(obj, dict):
        return {k: _inject_ids(v, key_to_id) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_inject_ids(v, key_to_id) for v in obj]
    if obj == "<placeholder>":
        return next(iter(key_to_id.values()), obj)
    return obj
