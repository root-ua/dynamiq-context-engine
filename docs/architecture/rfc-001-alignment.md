# RFC-001 v3 alignment — current state

This document maps each load-bearing RFC-001 v3 section to the
corresponding code in this repo. Rows are marked **implemented**,
**partial**, **deferred**, or **out of scope** (explicit prior).

Last updated: 2026-05-14 (Phase R–Z: connector removal + DX + skills + playground + comparison docs + production hardening)

## Section-by-section

| RFC § | Concept | Status | Code |
|---|---|---|---|
| §7 | Connector framework | **removed** (Phase R) | Ingestion is now the calling agent's job. The platform stops where the graph starts. Migration `20260514_0001_drop_connectors.py` removes `connector_instance`, `user_external_identity`, `episode_acl`, and the connector columns on `episode`. |
| §10 | Unified principal namespace | **simplified to workspace + labels** (Phase R) | Workspace RLS + sensitivity labels are the entire ACL surface. The per-source ACL projection is gone with the connector framework. |
| §11.4 | Sensitivity labels + policy | **implemented** | `sensitivity_label`, `episode_label`, `edge_label`, `label_policy` tables; `app/domain/sensitivity.py`; integrated into `app/retrieval/hybrid.py` |
| §11.5 | Source re-check on top-N | **removed** (Phase R) | The platform doesn't pull source data itself any more, so there's nothing to re-check. The `workspace.high_sensitivity` column is kept as a hint to calling agents. |
| §12 | Bi-temporal facts | **implemented** | `edge.valid_time` + `edge.sys_time` as `tstzrange` + GiST (`20260421_0001_initial_schema.py:262-282`); contradictor closes the prior fact at the new fact's `valid_from` |
| §12-13 | OWL/SHACL/SPARQL/RDF triples | **out of scope** | Locked-in prior: Postgres typed property graph + JSON-Schema validation. JSON-LD at the API boundary is the standards-compatible escape hatch (see PROV-O §17). |
| §15.2 | Per-class confidence thresholds + review queue | **implemented** | `extraction_policy` table, `pending_fact` table; `edge.propose_fact` routes by threshold; `/api/proposals` review queue; `/review` UI |
| §16 | Entity resolution (cascade) | **implemented** | `app/domain/entity_resolver.py` — 3 tiers (rules / trigram / LLM); `entity_external_ref` for stable IDs; `entity_resolution_decision` LLM-verdict cache |
| §17 | PROV-O provenance | **implemented** | `prov_activity` table; `app/domain/provenance.py` emits JSON-LD with `prov:` namespace; every extraction/contradiction/manual_edit attributes to one activity |
| §18 | Hybrid retrieval | **implemented** | RRF over vector+FTS+trigram + 1-hop graph expand + MMR (`app/retrieval/hybrid.py`); cross-encoder rerank available behind `RERANKER_ENABLED` flag (`app/retrieval/rerank.py`) |
| §19 | Kinetic actions | **implemented** | `action_type` + `action_invocation` tables; `app/domain/action.py` (idempotency, role gate, approval gate); first action: `attach_evidence_to_fact` |
| §20 | MCP server | **implemented + verified** | 22 tools (`app/api/mcp/tools.py`); full happy-path matrix covered by `test_scenario_mcp_agent.py::test_mcp_tool_happy_path` (parametrized over every tool); end-to-end agent flows (provenance round-trip, ACL filter, approval workflow, action idempotency, get_fact, agent-to-agent provenance) in same file + per-persona suites |
| §22 | Audit log | **implemented** | `audit_log` table; every state-changing path writes a row |
| §23 | Targets (100 QPS sustained) | **n/a** | Current single-node deploy. Kafka substrate explicitly deferred. |

## Phase R–Z (final production-readiness pass)

Architectural pivot:
- **R. Connector removal.** The platform owned a connector framework
  (Drive + Notion mock connectors, ACL snapshot, source-recheck) that
  blurred the product story. Removed: `backend/app/connectors/`, the
  REST `connectors` / `identity` / `sources` endpoints, the crawler
  worker, the per-source `episode_acl` and `user_external_identity`
  tables, the connector-coupled columns on `episode`, and every
  frontend page that surfaced them. Migration `20260514_0001` does
  the drop. Visibility now collapses to workspace RLS + sensitivity
  label policy.

Adjacent work, in dependency order:
- **S. DX + dependency tightening.** MinIO image pinned, `.nvmrc`,
  Python deps bumped, top-level `Makefile`, README rewrite around an
  explicit Quick Start, `CONTRIBUTING.md`, audited `.env.example`.
- **T. Agent skills library.** `skills/` folder with one `SKILL.md`
  per capability: `querying-with-confidence`, `ingesting-facts`,
  `agent-to-agent-provenance`, `governance-labels`,
  `action-invocation`, `time-travel-queries`,
  `reviewing-pending-facts`. Drop-in for Claude Code.
- **U. Chat-style playground.** New `POST /api/playground/chat`
  SSE route runs a real Claude agent with the platform's MCP tools
  registered. Frontend page at `/[workspace]/playground` shows the
  chat on the left and the tool-call timeline on the right.
- **V. MCP auth tightening.** Token rotation endpoint
  (`POST /agent-tokens/:id/rotate`), in-memory per-token rate limit
  on `/api/mcp/*` (default 60 req/min, override via
  `MCP_RATE_LIMIT_RPM`). Token `last_used_at` is updated on every
  successful verify.
- **W. Live LLM end-to-end test.** New `@pytest.mark.live_llm`
  marker; `backend/tests/test_scenario_live_llm.py` makes a real
  Anthropic call (~$0.05) and asserts the resulting facts land.
  CLI counterpart in `examples/01-claude-builds-kg.py`.
- **X. Comparison docs.** `docs/comparison/` — README + per-vendor
  long-form vs Zep, Mem0, LangChain Memory (Memori), Cognee. Honest
  about our weaknesses (no SPARQL, no embedded RAG pipeline).
- **Y. Production hardening.** Workspace deletion cascade test
  (`test_workspace_cascade.py`), `/api/version` endpoint returning
  git sha + schema version, CI workflow updated to exclude live_llm.
- **Z. Final validation.** `pytest -m "not live_llm"` green;
  ruff + mypy + web `pnpm check` green; cold-start smoke <60s.

## Phase N–Q additions (standards depth + agent-first surface)

Standards:
- **N1–N5** — JSON-LD content negotiation across entity / edge /
  episode / ontology / graph endpoints. `Accept: application/ld+json`
  (or `?format=jsonld`) returns a JSON-LD doc with `@context` carrying
  `prov:`, `owl:`, `rdfs:`, `skos:`, `xsd:`, and the Dynamiq-private
  `dce:` namespace. Entity types render as `owl:Class` with
  `rdfs:subClassOf`; relations as `owl:ObjectProperty` with
  `rdfs:domain/range` and `owl:inverseOf`; canonical/aliases as
  `skos:prefLabel/altLabel`; merged entities and external_refs surface
  as `owl:sameAs`. No new triple store.

Agent surface:
- **O1** — `get_fact(subject, predicate, object?, as_of?,
  require_min_confidence?)` MCP tool. Decision-support shortcut
  returning one structured fact with `confidence`, `freshness_days`,
  label slugs, and the PROV-O bundle attached. Returns `{multiple:
  true, candidates: [...]}` when several values exist.
- **O2** — `search_memory` hits now carry `payload.confidence`,
  `payload.freshness_days`, `payload.label_slugs`, and
  `payload.policy_warnings`. Single batched query, no N+1.
- **O3** — `prov_activity_derivation` table + `link_derivation` /
  `derivation_chain` helpers. `add_fact` / `add_episode` accept
  `derived_from_activity_ids=[...]` so meta-agents can record
  cross-agent `wasDerivedFrom` chains.

Wiring (load-bearing):
- **P1** — extraction now populates `entity_external_ref` with
  connector file-id + extracted props (email/slug/wikidata). Tier-1 of
  the entity resolver short-circuits on the second ingest.
- **P2** — `attach_evidence_to_fact` action writes a
  `prov_activity_derivation` row linking the action's activity to the
  edge's original activity, so `get_provenance` walks the chain.
- **P4** — source-recheck under `workspace.high_sensitivity` now fires
  from `graph.traverse` and `edge.live_edges` / `history` too, not
  just hybrid search.
- **P5** — retrieval pipeline order corrected to: RRF → label-policy
  filter → source-recheck → reranker → MMR.

Persona scenarios (`@pytest.mark.scenario`):
- **Q1** — mining agent: connector ingest + Tier-1 short-circuit.
- **Q2** — meta-agent: agent A → agent B `wasDerivedFrom` chain.
- **Q3** — functional CFO agent: `get_fact` with confidence, freshness,
  min-confidence gate, payload enrichment in search.
- **Q4** — governance chain: label drop for editor + high-sensitivity
  recheck in graph traversal.
- **Q5** — JSON-LD content negotiation across the read surface.
- **Q6** — multi-agent contradiction: exactly one survivor when two
  agents write conflicting high-stakes facts concurrently.

Bonus correctness fixes uncovered while wiring O1:
- Several `valid_time @> now()` clauses (in `edge.live_edges`,
  `retrieval.graph`, `retrieval.hybrid`) switched to
  `clock_timestamp()` so facts inserted in the same transaction are
  visible to the search/get path immediately.

Backend suite: **158 passed, 1 skipped** (was 135 at the end of the
TDD pass; +23 from Phase N–Q).

## Phase J–M additions (TDD correctness + scenario coverage pass)

Bug fixes (red → green TDD):
- **J1** `merge_entities` now invokes `cluster_is_safe_to_merge` —
  refuses an LLM-driven cluster collapse over 10 entities when edges
  are weak-confidence. New `EntityMergeUnsafeError` + `merge_cluster`
  helper.
- **J2** MCP `add_fact` / `add_episode` open a `prov_activity` row so
  agent-authored facts carry full provenance.
- **J3** Admin / owner / service principals **bypass** label policies,
  matching the ACL bypass shape — the two governance layers now agree.
- **J4** `approve_proposal` refuses to materialize an edge if the
  source episode was deleted; raises with `source_episode_missing`.
- **bonus** Conflict-guard in `propose_fact` switched from `now()` to
  `clock_timestamp()` so the high-stakes contradiction check fires
  even when both writes happen in the same transaction.

Test coverage (Phase K + L scenarios):
- 9 knowledge-worker scenarios in `tests/test_scenario_knowledge_worker.py`
  (Drive ingest + ACL, bi-temporal as-of, entity timeline, low-conf
  review + approve, high-stakes contradiction, label drop, source
  re-check, revision restore, workspace export round-trip).
- 30 AI-agent / MCP scenarios in `tests/test_scenario_mcp_agent.py`
  including a 21-tool parametrized happy-path matrix, provenance
  round-trip, approval workflow, action idempotency, ACL filter, and
  label drop via the MCP surface.
- Fixtures: `enterprise_workspace`, `stub_reranker`, in-process Arq
  drain (`tests/fixtures/`).
- New `@pytest.mark.scenario` marker; `pytest -m scenario` runs the
  39 scenario tests, `pytest -m "not scenario"` skips them.

Backend suite: **127 passed, 1 skipped** (was 80 at start of the
production-readiness pass).

## Phase F–H additions (production-readiness pass)

- **UI for B/C/D**: sensitivity labels manager + policy editor under the
  Ontology page; kinetic actions page (`/actions`); provenance pill +
  JSON-LD modal on the entity edge timeline; high-sensitivity toggle in
  workspace settings.
- **Data export** (GDPR): `POST /api/workspaces/:id/export`,
  `POST /api/me/export`; Arq job dumps gzipped JSONL to S3/MinIO with
  24h pre-signed URL; UI button in Settings → Data.
- **Bulk operations** on the review queue:
  `POST /api/proposals/bulk-{approve,reject}`,
  `POST /api/labels/:slug/bulk-assign`; review page sticky footer.
- **Document version history**: `document_revision` table +
  `snapshot_revision`/`restore_revision` domain calls + REST endpoints
  under `/api/documents/:id/revisions`; `RevisionPanel` UI.
- **Cross-encoder reranker**: optional, feature-flagged off by default.
- **Notion connector**: registered alongside Drive; mock mode complete,
  real OAuth scaffolded.
- **Ops slice**: `/ready` endpoint separate from `/health`; worker
  SIGTERM graceful drain (`WORKER_DRAIN_SECONDS`); audit-log retention
  cron (`AUDIT_LOG_RETENTION_DAYS`); structlog PII redaction processor;
  one-off `backfill_actions` script for pre-Phase-D workspaces.

## Out of scope (explicit deferrals)

- **Leiden/Louvain community subgraph**, intent-driven candidate routing.
- **SpiceDB / OpenFGA** — current per-source-ACL + workspace RLS + label policy covers ~80% of value at <5% of operational cost.
- **Kafka event substrate** — current Arq queue is sufficient at target scale (§23: 100 QPS sustained).
- **Connector breadth beyond Drive** — schedule M5-equivalent separately.
- **Full OWL reasoners, native SPARQL endpoint** — explicit prior.
  We sit between RDFS-Plus and OWL 2 RL: typed entities, relation
  hierarchies, inverse / symmetric / transitive flags. We do NOT
  ship a SPARQL endpoint or an OWL DL reasoner. JSON-LD at the API
  boundary is the standards-compatible escape hatch — agents that
  need a graph view get it via:
  - `GET /api/entities/{id}` with `Accept: application/ld+json` (the
    full PROV-O / OWL / SKOS bundle for an entity).
  - `graph_query` MCP tool — n-hop traversal with predicate / type
    filters and bi-temporal `as_of_valid`. This is the closest
    equivalent to SPARQL triple-pattern matching most workloads
    actually need.
  - `as_of_query` MCP tool — bi-temporal point-in-time view.
  If a real SPARQL endpoint is a hard requirement, pair Dynamiq with
  Cognee or Oxigraph behind a sync job; we'd consider a thin
  read-side adapter on customer ask, but it's not on the default
  roadmap.
- **Block-level ACL** — edges and episodes carry per-fact `allowed_principals[]`; block tables not yet wired.

## How to verify

```bash
docker compose down -v && docker compose up --build   # all 6 migrations apply cleanly
cd backend && uv run --extra dev pytest               # 80 passing as of this writing
cd ../web && pnpm typecheck && pnpm test:e2e          # extended smoke flow green
```

The MCP surface exposes the new tools at `POST /api/mcp/rpc` with
`tools/list`.
