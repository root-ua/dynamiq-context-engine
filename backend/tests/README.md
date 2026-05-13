# Backend test suite

## Run everything

```bash
docker compose up -d postgres redis minio
cd backend
POSTGRES_URL=postgresql+asyncpg://memory:memory@localhost:55432/memory \
POSTGRES_SYNC_URL=postgresql://memory:memory@localhost:55432/memory \
JWT_SECRET=test-very-long-secret-key-for-jwt-signing-32b \
ANTHROPIC_API_KEY=test \
CONNECTOR_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
MOCK_NOTION=1 MOCK_DRIVE=1 \
S3_ENDPOINT=http://localhost:59000 \
ONTOLOGY_SEED_PATH=$PWD/../seeds/ontology.yaml \
uv run --extra dev pytest
```

127 tests pass, 1 skipped.

## Test layout

| File | Scope |
|---|---|
| `test_acl.py`, `test_security_multitenancy.py` | Workspace boundary + ACL filter unit tests |
| `test_bitemporal.py` | Bi-temporal invariants (`valid_time` × `sys_time`) |
| `test_ontology.py` | Ontology CRUD + JSON-Schema validation |
| `test_entity.py`, `test_entity_merge_safety.py` | Entity domain (J1 safeguard) |
| `test_entity_resolver.py` | Three-tier resolution cascade |
| `test_proposals.py`, `test_sensitivity_labels.py`, `test_actions.py`, `test_provenance.py` | Phase A–D feature units |
| `test_mcp.py` | MCP tool registry + agent provenance (J2) |
| `test_notion_connector.py`, `test_drive_e2e.py` | Connector framework |
| `test_rest_end_to_end.py` | REST surface smoke |
| **`test_scenario_knowledge_worker.py`** | **Phase K — knowledge-worker scenarios** (9 tests) |
| **`test_scenario_mcp_agent.py`** | **Phase L — AI-agent scenarios** (30 tests, incl. 21-tool parametrized matrix) |

## The `scenario` marker

`@pytest.mark.scenario` flags tests that exercise full enterprise
flows (Drive ingest → search → ACL → label policy → provenance round-
trip, etc.). They hit a real Postgres + Redis + MinIO and take longer
than unit tests.

Run just scenarios:

```bash
uv run --extra dev pytest -m scenario
```

Run just unit tests (skip scenarios):

```bash
uv run --extra dev pytest -m "not scenario"
```

## Scenario fixtures

Defined in `tests/fixtures/`:

* **`enterprise_workspace`** — pre-seeded workspace with 3 users at
  different roles (owner/admin/editor), Google identities bridged to
  the Drive mock's ACL principals (`alice@acme.com`, `carol@acme.com`,
  `admin@acme.com`), registered Drive + Notion connector_instances in
  mock mode, built-in actions, and a default
  `mutually_exclusive([pii, public]) → drop` policy.
* **`stub_reranker`** — injects a deterministic score function into
  `app.retrieval.rerank` so tests can assert "rerank reordered the
  candidates" without pulling the real cross-encoder model.
* **`fixtures.arq.run_extraction_inline(...)`** — direct in-process
  call to the extraction Arq handler so tests don't need a running
  worker.

## RLS hygiene note

The default `memory` Postgres role used by tests is a **superuser**
with `BYPASSRLS=t`. Migrations declare RLS policies but they do NOT
filter rows for this role. All ACL tests therefore exercise the
**application-layer SQL clauses** in `app/auth/acl.py` (which build
explicit WHERE fragments) — RLS is defence-in-depth, not the test
boundary.

App code that *implicitly* relies on RLS to scope a query will silently
leak across workspaces during tests. New code paths that depend on
isolation should add an explicit workspace filter or pass through
`session_scope(workspace_id=...)` + an SQL `WHERE workspace_id = ...`
predicate.
