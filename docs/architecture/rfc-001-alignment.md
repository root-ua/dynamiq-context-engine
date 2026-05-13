# RFC-001 v3 alignment — current state

This document maps each load-bearing RFC-001 v3 section to the
corresponding code in this repo. Rows are marked **implemented**,
**partial**, **deferred**, or **out of scope** (explicit prior).

Last updated: 2026-05-13 (Phase A–D + production-readiness pass F–H + TDD pass J–M)

## Section-by-section

| RFC § | Concept | Status | Code |
|---|---|---|---|
| §7 | Connector framework | **implemented** | `backend/app/connectors/base.py`, `registry.py`; Drive in `google_drive.py`; Notion in `notion.py` (mock-mode complete, real OAuth stubbed) |
| §10 | Unified principal namespace | **partial** | `episode_acl(principal_kind, principal_external_id)` (`20260508_0001_source_acl_drive.py`), with `user|group|domain|anyone`; `edge.allowed_principals[]` / `episode.allowed_principals[]` denormalized fast path (`20260513_0003_sensitivity_and_acl.py`). Not yet generalized to blocks. |
| §11.4 | Sensitivity labels + policy | **implemented** | `sensitivity_label`, `episode_label`, `edge_label`, `label_policy` tables; `app/domain/sensitivity.py`; integrated into `app/retrieval/hybrid.py` |
| §11.5 | Source re-check on top-N | **implemented** | `CrawlerConnector.check_access` hook (`base.py`); `_source_recheck_top_n` in `app/retrieval/hybrid.py`; gated on `workspace.high_sensitivity` |
| §12 | Bi-temporal facts | **implemented** | `edge.valid_time` + `edge.sys_time` as `tstzrange` + GiST (`20260421_0001_initial_schema.py:262-282`); contradictor closes the prior fact at the new fact's `valid_from` |
| §12-13 | OWL/SHACL/SPARQL/RDF triples | **out of scope** | Locked-in prior: Postgres typed property graph + JSON-Schema validation. JSON-LD at the API boundary is the standards-compatible escape hatch (see PROV-O §17). |
| §15.2 | Per-class confidence thresholds + review queue | **implemented** | `extraction_policy` table, `pending_fact` table; `edge.propose_fact` routes by threshold; `/api/proposals` review queue; `/review` UI |
| §16 | Entity resolution (cascade) | **implemented** | `app/domain/entity_resolver.py` — 3 tiers (rules / trigram / LLM); `entity_external_ref` for stable IDs; `entity_resolution_decision` LLM-verdict cache |
| §17 | PROV-O provenance | **implemented** | `prov_activity` table; `app/domain/provenance.py` emits JSON-LD with `prov:` namespace; every extraction/contradiction/manual_edit attributes to one activity |
| §18 | Hybrid retrieval | **implemented** | RRF over vector+FTS+trigram + 1-hop graph expand + MMR (`app/retrieval/hybrid.py`); cross-encoder rerank available behind `RERANKER_ENABLED` flag (`app/retrieval/rerank.py`) |
| §19 | Kinetic actions | **implemented** | `action_type` + `action_invocation` tables; `app/domain/action.py` (idempotency, role gate, approval gate); first action: `attach_evidence_to_fact` |
| §20 | MCP server | **implemented + verified** | 21 tools (`app/api/mcp/tools.py`); full happy-path matrix covered by `test_scenario_mcp_agent.py::test_mcp_tool_happy_path` (parametrized over every tool); end-to-end agent flows (provenance round-trip, ACL filter, approval workflow, action idempotency) in same file |
| §22 | Audit log | **implemented** | `audit_log` table; every state-changing path writes a row |
| §23 | Targets (100 QPS sustained) | **n/a** | Current single-node deploy. Kafka substrate explicitly deferred. |

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
- **Full OWL reasoners, native SPARQL endpoint** — explicit prior. JSON-LD at the API boundary is the standards-compatible escape hatch.
- **Block-level ACL** — edges and episodes carry per-fact `allowed_principals[]`; block tables not yet wired.

## How to verify

```bash
docker compose down -v && docker compose up --build   # all 6 migrations apply cleanly
cd backend && uv run --extra dev pytest               # 80 passing as of this writing
cd ../web && pnpm typecheck && pnpm test:e2e          # extended smoke flow green
```

The MCP surface exposes the new tools at `POST /api/mcp/rpc` with
`tools/list`.
