# Dynamiq Context Engine — Technical Report

**Scope:** end-to-end mechanics of the platform — how users (humans and agents) interact, how information lands and is shaped, how facts are validated, and how queries actually run.

**Style:** every claim is anchored to a file path; minor implementation details are summarized; verbatim SQL is quoted when it carries the algorithm.

---

## 0. System at a glance

Dynamiq is a self-hostable **agent-first memory platform**: a typed, bi-temporal property graph stored entirely in Postgres 17 with a W3C PROV-O provenance layer, exposed via an MCP server (22 tools) for agents and a Notion/Obsidian-style web app for humans. One database backs both surfaces; everything passes through the same audit and RLS plumbing.

**Stack:**

| Layer | Tech |
|---|---|
| Storage | Postgres 17 + pgvector + pg_trgm + btree_gist + ltree + citext + pgcrypto |
| Blob | MinIO (S3-compatible) — **exports only**, not raw documents |
| Backend | FastAPI + async SQLAlchemy 2.x + Pydantic v2 |
| Workers | Arq (Redis-backed queue), 8-worker pool with graceful drain |
| Auth | Better Auth (sessions) + dq-prefixed agent tokens |
| LLM | Anthropic (Claude haiku for extraction, configurable) |
| Web | Next.js App Router + BlockNote + Yjs CRDT |
| Collab | Hocuspocus WebSocket server (TypeScript) |
| Compose | Docker — postgres / redis / minio / backend / worker / hocuspocus / web |

**Architecture sketch:**

```
                Humans                          Agents (Claude, Cursor, custom)
                  │                                       │
       ┌──────────▼──────────┐                  ┌─────────▼──────────┐
       │  Next.js web app    │                  │  MCP (SSE/JSON-RPC) │
       │  (BlockNote + Yjs)  │                  │   /  REST           │
       └──────────┬──────────┘                  └─────────┬──────────┘
                  │ HTTP + WS                              │ HTTP
       ┌──────────▼─────────┐    ┌──────────────────────────▼────────┐
       │  Hocuspocus collab │    │       FastAPI backend             │
       │  (Yjs binary state)│    │  Pydantic → Domain → SQLAlchemy   │
       └──────────┬─────────┘    └─────┬──────────────────┬──────────┘
                  │                    │ enqueue (Arq)    │
                  │                    ▼                  │
                  │              ┌──────────┐             │
                  │              │ Worker   │  LLM calls  │
                  │              │ pool     ├────────────►│ Anthropic
                  │              └─────┬────┘             │
                  ▼                    ▼                  ▼
       ┌─────────────────────────────────────────────────────────────┐
       │ Postgres 17 + pgvector + pg_trgm + btree_gist + ltree       │
       │   tenant tables: workspace_id + ENABLE+FORCE RLS            │
       └─────────────────────────────────────────────────────────────┘
                                       │ presigned URLs
                                       ▼
                                  ┌──────────┐
                                  │  MinIO   │  (exports only)
                                  └──────────┘
```

---

## 1. How users interact

There are two distinct user classes and a third intermediate (collab server). Both human and agent paths terminate in the same FastAPI handlers; the API itself is the integration surface.

### 1.1 Web app — humans

Next.js App Router under [web/app/](web/app/), with route groups `(auth)` / `(app)`. Pages:

| Route | Purpose |
|---|---|
| `/login`, `/signup`, `/verify`, `/password-reset` | Auth via Better Auth (email + password, mandatory email verification) |
| `/onboarding` | Create first workspace; pick ontology mode (`strict` / `flexible` / `auto`) |
| `/invite/[token]` | Join workspace via mint-once invite token |
| `/[workspace]/entities` | Entity browser, filter by type |
| `/[workspace]/documents` & `/documents/[id]` | Block editor for Notion-style prose |
| `/[workspace]/graph` | Typed property-graph visualizer (seed → n-hop) |
| `/[workspace]/episodes` | Raw ingestion logs |
| `/[workspace]/playground` | Streamed Claude chat with file upload |
| `/[workspace]/ontology` | Entity/relation type editor |
| `/[workspace]/review` | Pending-fact review queue |
| `/[workspace]/search` | Hybrid search UI |
| `/[workspace]/actions` | Kinetic-action catalog & invocation log |
| `/[workspace]/activity` | Audit log (agent sessions, tool calls, edits) |
| `/[workspace]/settings/{agents,members,workspace}` | RBAC, token management |

**Block editor stack** ([web/components/editor/](web/components/editor/)): BlockNote (open-source Notion-like editor) on top of **Yjs** (CRDT). The Yjs binary state is persisted in `document.yjs_state` (bytea column in Postgres). The editor supports @-mention autocomplete to entities, slash commands, and color-coded multi-user cursors via Hocuspocus.

**Playground** ([backend/app/api/rest/playground.py](backend/app/api/rest/playground.py)): a real Claude chat with all 22 MCP tools registered. Streams server-sent events: `text_delta`, `tool_call`, `tool_result`, `done`, `error`. Loop cap is 16 iterations. Files (PDF/image/text) are forwarded as Anthropic native content blocks — Claude reads them and decides which facts to record via MCP.

### 1.2 MCP server — agents

[backend/app/api/mcp/tools.py](backend/app/api/mcp/tools.py) (902 LOC) exposes **22 tools** over JSON-RPC SSE (Claude Desktop, Cursor, etc.) and a REST `/mcp/invoke` shim. Each tool's Pydantic schema doubles as its JSON Schema declaration.

| Category | Tools |
|---|---|
| Retrieval | `search_memory`, `get_entity`, `get_fact`, `graph_query`, `as_of_query`, `get_provenance` |
| Ingestion | `add_fact`, `add_episode`, `invalidate_fact`, `update_entity` |
| Ontology | `ontology_describe`, `create_entity_type`, `create_relation_type`, `propose_ontology` |
| Review | `list_proposals`, `approve_proposal`, `reject_proposal` |
| Governance | `list_labels`, `assign_label` |
| Actions | `list_action_types`, `execute_action`, `list_action_invocations` |

Every tool invocation is logged to `agent_tool_call` (workspace, session, tool name, input, output, latency).

### 1.3 REST API

[backend/app/api/rest/](backend/app/api/rest/) — same domain layer, REST-shaped: `entities.py`, `edges.py`, `episodes.py`, `documents.py`, `ontology.py`, `proposals.py`, `provenance.py`, `labels.py`, `actions.py`, `workspaces.py`, `agent_tokens.py`, plus content negotiation for JSON-LD (`Accept: application/ld+json` or `?format=jsonld`) via [content_negotiation.py](backend/app/api/content_negotiation.py).

### 1.4 Auth & principal model

[backend/app/auth/](backend/app/auth/):

- **Session JWT** — for humans, issued by Better Auth via `/api/auth/token`. Claims: `sub`, `workspace_id`, `role`, `email`, `aud` (MCP resource URL per RFC 8707).
- **Agent token** — long-lived bearer, prefix `dq_`. Hashed at rest, plaintext shown once. Scopes: `mcp` (default) or `rest`. Kinds: `service` (bypasses per-source ACL) or `user` (acts as the minting user).
- **Principal** dataclass: `user_id`, `email`, `workspace_id`, `role` (`owner|admin|editor|viewer`), `kind` (`user|service`), raw `claims`.

Roles gate endpoints via `@require_workspace_role(...)` decorators. Membership verified against `workspace_member` at every request.

### 1.5 Collab server

[collab/src/server.ts](collab/src/server.ts) is a Hocuspocus WebSocket server. On every CRDT change it (a) persists the Yjs binary state into `document.yjs_state`, and (b) projects the CRDT to a queryable BlockNote block tree which it POSTs to `/api/documents/{id}/blocks`. Bearer JWT auth on connect; rejects unauthorized sessions.

---

## 2. How information is stored

Postgres 17 with six extensions: `vector`, `pg_trgm`, `btree_gist`, `ltree`, `citext`, `pgcrypto` (see [ops/postgres/init.sql](ops/postgres/init.sql)). Roughly **29 tenant tables**, all `workspace_id`-scoped and behind RLS.

### 2.1 Tenancy

- `workspace` — slugged, soft-deletable root.
- `app_user` — separate from Better Auth's `user` table; this is the in-app identity.
- `workspace_member` — `(workspace_id, user_id, role)` with `role` in `owner|admin|editor|viewer`.
- `workspace_invite` — mint-once tokens with expiry.
- `agent_token` — hashed bearer tokens with `kind ∈ {service, user}` and a scope list.

`workspace` / `app_user` / `workspace_member` are shared (not RLS'd); everything else is RLS-forced.

### 2.2 Ontology

```sql
CREATE TABLE entity_type (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  slug text NOT NULL,
  extends_id uuid REFERENCES entity_type(id),
  hierarchy ltree NOT NULL,
  schema jsonb NOT NULL DEFAULT '{"type":"object","properties":{}}'::jsonb,
  UNIQUE (workspace_id, slug)
);
CREATE INDEX entity_type_hierarchy_gist ON entity_type USING gist (hierarchy);
```

A trigger maintains `hierarchy = parent.hierarchy || slug`, so a path like `root.person.employee.contractor` becomes ltree-queryable: `WHERE et.hierarchy <@ :root_path` returns all subtypes.

`relation_type` similarly carries `domain_type_id`, `range_type_id`, `cardinality_subject/object ∈ {one, many}`, plus flags: `symmetric`, `transitive`, `temporal`, `high_stakes`, `inverse_of_id`.

### 2.3 Bi-temporal graph core

The defining shape. From [20260421_0001_initial_schema.py:262-282](backend/app/db/migrations/versions/20260421_0001_initial_schema.py#L262-L282):

```sql
valid_time tstzrange NOT NULL DEFAULT tstzrange(now(), 'infinity', '[)'),
sys_time   tstzrange NOT NULL DEFAULT tstzrange(now(), 'infinity', '[)'),
...
CREATE INDEX edge_valid_time_gist ON edge USING gist (valid_time);
CREATE INDEX edge_sys_time_gist   ON edge USING gist (sys_time);
CREATE INDEX edge_subject_predicate_valid_gist
  ON edge USING gist (subject_id, predicate_id, valid_time)
  WHERE upper(sys_time) = 'infinity';
```

- `valid_time` — when the fact is true in the **world**.
- `sys_time` — when the **system believed** it.
- Both axes are independent `tstzrange` columns with GiST indexes for `@>` containment.
- "Live" rows have `upper(sys_time) = 'infinity'`. Closed rows stay in place — **invalidate, never delete**.
- `invalidated_by uuid` chains a new edge back to the one it superseded.

Same pattern on `entity_attribute` (per-entity properties that change over time).

### 2.4 Entities

```sql
entity(id, workspace_id, type_id, iri, canonical citext, aliases citext[],
       summary text, summary_embedding vector(1536),
       merged_into_id uuid, props jsonb, ...)
```

- `canonical` is `citext` so case-insensitive lookups are native.
- `summary_embedding` is HNSW-indexed (`m=16, ef_construction=64`, cosine ops).
- Trigram GIN on canonical/aliases for fuzzy search.
- `merged_into_id` records deduplication.

### 2.5 Documents & blocks

- `document` — 1:1 with an entity; holds the Yjs binary state.
- `block` — hierarchical (`parent_block_id`, `position numeric(40,20)` for fractional ordering). Contains `content jsonb`, `props jsonb`, `search_text text`, generated `search_tsv tsvector`.
- `block_entity_ref` — many-to-many entity mentions inside blocks.
- `document_revision` — snapshot copies of the block tree (jsonb) for restore.

### 2.6 Episodes (ingestion)

```sql
episode(id, workspace_id, source_kind, source_ref, occurred_at,
        content jsonb, content_text text,
        content_embedding vector(1536),
        processing_status text,  -- pending|processing|completed|failed
        deleted_at timestamptz,
        prov_activity_id uuid)
```

Episodes are the **non-lossy ground truth** that extraction reads from. Original content is stored inline in jsonb — no separate blob store for raw documents.

### 2.7 Provenance (W3C PROV-O)

[20260513_0001_provenance_and_proposals.py](backend/app/db/migrations/versions/20260513_0001_provenance_and_proposals.py):

```sql
CREATE TABLE prov_activity (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL,
  kind text CHECK (kind IN
    ('extraction','contradiction','manual_edit','merge',
     'action','seed','approval')),
  agent_kind text CHECK (agent_kind IN ('llm','user','system','connector')),
  agent_ref text,        -- model name / user id / system id
  agent_version text,
  inputs jsonb NOT NULL,
  outputs jsonb NOT NULL,
  started_at timestamptz, ended_at timestamptz,
  audit_log_id bigint REFERENCES audit_log(id)
);

ALTER TABLE edge             ADD COLUMN prov_activity_id uuid REFERENCES prov_activity(id);
ALTER TABLE entity_attribute ADD COLUMN prov_activity_id uuid;
ALTER TABLE episode          ADD COLUMN prov_activity_id uuid;
```

Plus cross-agent derivation chains ([20260513_0007_activity_derivation.py](backend/app/db/migrations/versions/20260513_0007_activity_derivation.py)):

```sql
CREATE TABLE prov_activity_derivation (
  workspace_id uuid NOT NULL,
  derived_activity_id  uuid NOT NULL REFERENCES prov_activity(id),
  upstream_activity_id uuid NOT NULL REFERENCES prov_activity(id),
  derivation_kind text DEFAULT 'derived'
    CHECK (derivation_kind IN ('derived','revised','quoted')),
  PRIMARY KEY (derived_activity_id, upstream_activity_id)
);
```

This is the **entity ← activity ← agent** PROV trinity, plus activity-to-activity links — what lets you answer "which model, run by which agent, on which episode, triggered by which upstream activity, produced this fact."

### 2.8 Sensitivity labels

```sql
CREATE TABLE sensitivity_label (
  id uuid PRIMARY KEY, workspace_id uuid NOT NULL,
  slug text NOT NULL, path ltree NOT NULL,
  UNIQUE (workspace_id, slug)
);
-- Many-to-many to edges and episodes:
CREATE TABLE edge_label    (edge_id uuid, label_id uuid, workspace_id uuid, ...);
CREATE TABLE episode_label (episode_id uuid, label_id uuid, ...);
-- Declarative policies evaluated in Python at retrieval time:
CREATE TABLE label_policy (
  workspace_id uuid NOT NULL, name text NOT NULL,
  rule jsonb NOT NULL,                -- e.g. {"kind":"mutually_exclusive","labels":[...]}
  action text CHECK (action IN ('drop','warn','block')),
  enabled boolean DEFAULT true
);
```

Labels are hierarchical (`pii.financial` is under `pii`). `workspace.high_sensitivity` exists in the schema but enforcement code is still partial.

### 2.9 Review queue, extraction policy, entity resolution

- `pending_fact` — shadow edges awaiting human review; `status ∈ {pending, approved, rejected, superseded}`; carries everything needed to materialize an `edge` on approval.
- `extraction_policy(entity_type_id?, relation_type_id?, min_confidence, auto_reject_below)` — per-(type or relation) thresholds with workspace default fallback.
- `entity_external_ref(workspace_id, kind, value citext) → entity_id` — exact-match resolution cache (email, slug, wikidata).
- `entity_resolution_decision(a_id, b_id, decision, confidence, rationale, agent_ref)` with `CHECK (a_id < b_id)` — caches LLM merge judgments to avoid re-judging the same pair.

### 2.10 Actions

`action_type` (input JSON Schema, `required_role`, `idempotency_required`, `requires_approval`, declared `side_effects`) plus `action_invocation` (per-execution rows with `status ∈ {pending, approved, executing, completed, failed, rejected}`, `idempotency_key`, `emitted_edge_id`, `prov_activity_id`). The unique constraint `(workspace_id, action_type_id, idempotency_key)` enforces idempotency at the DB level.

### 2.11 Audit log

`audit_log(actor_kind, actor_id, action, target_kind, target_id, diff jsonb, created_at)` — separate from `prov_activity`; this is the human-readable event stream. Retention configurable via `AUDIT_LOG_RETENTION_DAYS` (default 365), purged by a daily Arq cron.

### 2.12 Row-Level Security

Every tenant table runs:

```sql
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE  ROW LEVEL SECURITY;

CREATE POLICY {t}_ws_select ON {t} FOR SELECT
  USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
CREATE POLICY {t}_ws_modify ON {t} FOR ALL
  USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id())
  WITH CHECK (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
```

`FORCE` means even the table owner is subject. The context variable `app.current_workspace_id` is set per-transaction via `SET LOCAL` from the FastAPI session dependency (see §5.7) — it survives pgbouncer transaction mode.

### 2.13 Embeddings

| Embedded | Column | Index |
|---|---|---|
| Entity summary | `entity.summary_embedding` | HNSW cosine, m=16, ef_construction=64 |
| Fact text | `edge.fact_embedding` | HNSW cosine |
| Episode raw content | `episode.content_embedding` | HNSW cosine |

Dimension hardcoded to **1536** (text-embedding-3-small). Changing models requires a column-alter migration.

### 2.14 Blob storage

MinIO holds **exports only** (gzipped JSONL for workspace dumps and GDPR user-data dumps), referenced by `export_job.object_key` with presigned-URL expiry tracked in `download_expires_at`. Original document content stays in Postgres.

---

## 3. How information is constructed and retrieved

Two distinct flows: **ingestion** (write path that turns raw input into typed graph elements) and **retrieval** (read path that ranks and returns).

### 3.1 Ingestion — synchronous phase

[`add_episode`](backend/app/domain/episode.py) is the sync part:

1. Normalize content (string or dict → plain text).
2. Embed the text (1536-d) and store in `episode.content_embedding`.
3. `INSERT INTO episode (...) VALUES (..., processing_status='pending', ...)`.
4. Return the episode row to the caller immediately.

The MCP tool `_add_episode` then enqueues an Arq job: `enqueue_extraction(workspace_id, episode_id, actor_id)`.

### 3.2 Ingestion — asynchronous extraction

[backend/app/extraction/pipeline.py](backend/app/extraction/pipeline.py), `process_episode()`:

1. **Load** the episode.
2. **LLM extraction** via `llm.structured(schema=Extraction, temperature=0.1, max_tokens=4000)` — Claude (haiku by default for cost) returns typed `ExtractedEntity` and `ExtractedEdge` lists with local IDs for cross-fact linking. System prompt enforces "grounded in text" factuality + ISO-8601 date normalization.
3. **Ontology mode handling** — in `flexible` or `auto` mode the pipeline can auto-create missing entity/relation types via `_extend_ontology()`; in `strict` mode unknown types are dropped.
4. **Entity resolution** — see §3.3.
5. **Edge creation** — each extracted edge goes through `edge_mod.propose_fact()`, which routes by confidence (see §4.2).
6. **Status update** — episode → `completed` or `failed`.

### 3.3 Entity resolution (three-tier cascade)

[backend/app/domain/entity_resolver.py](backend/app/domain/entity_resolver.py) + [backend/app/llm/entity_resolver.py](backend/app/llm/entity_resolver.py):

**Tier 1 — Rules (deterministic):**
```sql
SELECT entity_id FROM entity_external_ref
WHERE (kind, value) = ANY(:candidate_refs);

SELECT e.id FROM entity e
WHERE lower(e.canonical) = lower(:name);
```
External refs (email, slug, wikidata Q-id) + canonical-name case-insensitive match. Conclusive on hit.

**Tier 2 — Trigram + semantic blocking:** `pg_trgm.similarity()` against top-50 candidates ordered by similarity DESC.
- `score >= 0.9` → MATCH.
- `score <= 0.3` → NO_MATCH.
- `0.3 < score < 0.9` → escalate.

**Tier 3 — LLM judge:** `judge_pair()` calls Claude haiku at `temperature=0` and returns `match | no_match | uncertain` with confidence. Result cached in `entity_resolution_decision` so the same pair is never re-judged. The constraint `CHECK (a_id < b_id)` enforces canonical ordering for the cache key.

**Cluster safeguard:** before merging, if the cluster `> 10` entities and any edge has weak confidence, the merge returns `(False, "cluster_too_large_with_weak_edges")` — human review required.

### 3.4 Workers

[backend/app/workers/jobs.py](backend/app/workers/jobs.py), Arq pool size 8 with `SIGTERM` graceful drain:

| Job | Purpose |
|---|---|
| `extract_episode` | The pipeline above |
| `propose_and_apply_ontology` | LLM auto-ontology proposal with optional auto-apply |
| `run_workspace_export` | Dump workspace to gzipped JSONL on MinIO |
| `run_user_export` | GDPR-style user-data dump |
| `purge_old_audit_log` | Daily cron, trims by retention window |

### 3.5 Hybrid retrieval

[backend/app/retrieval/hybrid.py](backend/app/retrieval/hybrid.py) is the heart of the read path. Four independent candidate streams over four entity kinds, fused, optionally reranked, then diversified.

**Streams** (each capped at 30–50 hits):

| Kind | Vector path | Text path |
|---|---|---|
| Entity | `e.summary_embedding <=> :emb` (cosine) | `similarity(canonical, :q)` + ILIKE on canonical/aliases |
| Edge | `e.fact_embedding <=> :emb` (cosine) | `similarity(fact, :q)` + ILIKE on fact |
| Episode | `episode.content_embedding <=> :emb` | `similarity(content_text, :q)` + ILIKE |
| Block | — | `ts_rank(search_tsv, plainto_tsquery('simple', :q))` |

Edges in vector & text paths carry temporal filter `valid_time @> clock_timestamp()` (or `@> :vt` for as-of) and the ACL clause from `edge_visibility_clause(principal, edge_alias='e')`.

**Fusion — Reciprocal Rank Fusion** (lines 574–592):

```python
contribution = 1.0 / (k + rank)   # k = 60
score[key]   = Σ contributions   # key = (kind, id), best wins on dup
```

**Cross-encoder rerank** (optional, [retrieval/rerank.py](backend/app/retrieval/rerank.py)): a SentenceTransformers `CrossEncoder` scores (query, passage) pairs on the top N (default 50). Lazy-loaded.

**Label-policy filter** runs **before** the reranker so sensitive results never reach the cross-encoder — see §4.6.

**MMR diversification** (lines 595–619):

```python
mmr = λ * relevance - (1 - λ) * max_similarity_to_chosen   # λ = 0.7
```

Similarity is Jaccard over word bags (tokens > 3 chars from title + snippet).

**Payload enrichment**: batched lookups attach `confidence`, `freshness_days` (from `lower(valid_time)`), and assigned `label_slugs` to each hit.

### 3.6 Graph traversal

[backend/app/retrieval/graph.py](backend/app/retrieval/graph.py), `traverse()`:

```sql
WITH RECURSIVE walk(id, distance, path) AS (
  SELECT id, 0, ARRAY[id] FROM entity
  WHERE id = ANY(:seeds) AND deleted_at IS NULL
  UNION ALL
  SELECT next_id::uuid, w.distance + 1, w.path || next_id::uuid
  FROM walk w
  JOIN edge e ON (forward_join)
  WHERE w.distance < :max_hops
    AND NOT (next_id::uuid = ANY(w.path))   -- cycle guard
)
SELECT DISTINCT ON (ent.id) ent.id, ent.iri, ent.canonical, et.slug, MIN(w.distance)
FROM walk w JOIN entity ent ON ent.id = w.id
            JOIN entity_type et ON et.id = ent.type_id
LIMIT :max_nodes;
```

Parameters: `seeds`, `max_hops` (default 2), `direction ∈ {out, in, both}`, optional `predicate_slugs`, `type_slugs`, `as_of_valid`, `principal` for ACL. Cycle detection via `NOT (next_id = ANY(path))`; node cap default 500.

When `graph_expand=true` is passed to hybrid search, returned entities get a 1-hop expansion to surface neighboring edges, marked with `payload["via"] = "graph_expand"`.

### 3.7 What runs sync vs async

| Sync (HTTP request) | Async (worker) |
|---|---|
| `add_episode` row insert + embedding | LLM extraction (`process_episode`) |
| `add_fact` direct write + contradictor | Workspace/user exports |
| Approve / reject pending fact | Audit-log retention purge |
| All retrieval queries | Ontology auto-proposal |
| Action invocation (when no approval) | — |

---

## 4. How information is validated

Five layers, in order of where they fire:

1. **Pydantic** at the HTTP boundary.
2. **Confidence triage** → edge / pending / rejected.
3. **Contradictor** for high-stakes predicates.
4. **Pending-fact review** by humans.
5. **Label policy** at retrieval.

Plus RLS at the DB layer cutting across everything.

### 4.1 Schema validation

Pydantic v2 models in [backend/app/api/rest/schemas.py](backend/app/api/rest/schemas.py) enforce shape and bounds (`confidence ∈ [0,1]`, etc.). The same models double as MCP tool JSON Schemas.

**Known gap:** `entity.props` is `jsonb` and is *not* validated against the entity-type's `schema` column at write time. `pg_jsonschema` is deferred to v1.1 ([ops/postgres/init.sql:10](ops/postgres/init.sql#L10)). Today the type's JSON Schema is informational.

### 4.2 Confidence-based triage

[backend/app/domain/proposals.py](backend/app/domain/proposals.py) `propose_fact()` is the choke point for any extractor-produced edge. It resolves thresholds with precedence:

```
relation-specific > entity-specific > workspace default > built-in defaults (0.7 / 0.3)
```

Routing:

| Confidence | Destination | Status |
|---|---|---|
| `≥ min_confidence` | `edge` (direct) | live |
| `auto_reject_below ≤ x < min_confidence` | `pending_fact` | `pending` |
| `< auto_reject_below` | `pending_fact` | `rejected` (kept for audit) |

### 4.3 Pending-fact review

[backend/app/api/rest/proposals.py](backend/app/api/rest/proposals.py):

- `GET /api/proposals?status=pending` — review queue.
- `POST /api/proposals/:id/approve` — requires editor+. Opens a `prov_activity(kind='approval')` attributed to the reviewer, calls `edge_mod.add_fact()` (re-running the contradictor and cardinality logic), updates the pending row to `approved` with `approved_edge_id`, writes `audit_log(action='proposal.approve')`.
- `POST /api/proposals/:id/reject` — stores reviewer + reason; row stays as audit evidence.

Tests: [backend/tests/test_proposals.py](backend/tests/test_proposals.py) covers all three routing paths plus approval/rejection.

### 4.4 Contradictor (high-stakes)

[backend/app/llm/contradictor.py](backend/app/llm/contradictor.py) only fires when `relation_type.high_stakes = true`. Mechanism:

1. Candidate selection — find ≤ 5 live edges with same `(subject_id, predicate_id)` and `fact_embedding` similarity above `contradictor_similarity_threshold` (default 0.85).
2. LLM verdict — Claude (`temperature=0.1`) returns `contradicts | supports | unrelated` with reasoning.
3. On `contradicts` — close the losing edge: `sys_time` upper set to `clock_timestamp()`, `valid_time` upper set to the new fact's `valid_from`. Old row stays. Both sit in the table; only the new one shows under `upper(sys_time) = 'infinity'`. Audit logged with reasoning.

**High-stakes routing in `propose_fact`** (lines 269–311): if a fact would close an existing edge under `cardinality_object=one` + `high_stakes`, it bypasses confidence and is queued for review regardless. Approval re-runs `add_fact()` under user authorization, with the contradictor.

### 4.5 Action approval

[backend/app/domain/action.py](backend/app/domain/action.py) `execute_action()`:

1. `jsonschema.validate(input, action.input_schema)`.
2. Role check: principal.role ≥ `action.required_role`.
3. Idempotency check: unique `(workspace_id, action_type_id, idempotency_key)` — duplicate returns the cached prior result.
4. If `requires_approval`: insert with `status='pending'`, return. `approve_invocation` (admin/owner only) transitions to `executing` and runs the handler. `reject_invocation` sets `rejected` with a reason.

Built-in action: `attach_evidence_to_fact` — appends to `edge.props.evidence[]`, requires editor, no approval needed.

### 4.6 Label-policy enforcement

[backend/app/domain/sensitivity.py](backend/app/domain/sensitivity.py) `apply_label_policy()`:

- **Bypass** if `principal.role in {'owner','admin'}` or `principal.kind == 'service'`.
- Batched label lookup over candidate edge/episode ids.
- Rule evaluation (Python, not SQL):
  - `mutually_exclusive` — drop if candidate carries ≥ 2 labels from a forbidden set.
  - `requires_role` — drop if labeled and principal lacks the role.
- Returns `(kept, summary)` where `summary` tracks dropped count + triggered policy names.

Called in the hybrid search pipeline **before** reranking. **Not** applied to write-time edge insertion — labels can only be assigned after creation via `assign_label`.

### 4.7 RLS as the floor

Every workspace-scoped query first passes through the RLS policy: `workspace_id = current_setting('app.current_workspace_id')::uuid`. The application's label policy is a *second* gate over the rows RLS already allowed through.

---

## 5. How queries work

The mechanics under each MCP tool — focused on the actual SQL and algorithm, not the API shape.

### 5.1 `search_memory` (`_search_memory` in [tools.py:230-242](backend/app/api/mcp/tools.py#L230-L242))

Thin wrapper around `hybrid.search()` (§3.5). Optional parameters:

- `include_kinds` — subset of `{entity, edge, episode, block}`.
- `entity_type` — slug or hierarchy-root; uses ltree containment: `WHERE et.hierarchy <@ root.hierarchy`.
- `as_of_valid` — flips edge queries from `@> clock_timestamp()` to `@> :vt`.
- `graph_expand` — adds 1-hop neighboring edges around entity hits.

Result rows carry `kind`, `id`, `title`, `snippet`, `score`, plus enriched payload (confidence, freshness, labels, policy warnings).

### 5.2 `get_entity` and `get_fact` (direct lookup)

`get_entity` ([tools.py:245-260](backend/app/api/mcp/tools.py#L245-L260)) — fetch by id / IRI / canonical, optionally include:

- `edges_out` / `edges_in` — live edges only.
- `history_out` / `history_in` — all rows (closed + live) by `lower(sys_time) DESC`.
- `backlinks` — documents that @-mention the entity.

No ranking, no label policy.

`get_fact` (lines 529–651) — decision-support lookup for `(subject, predicate, [object])`:

1. Resolve subject + predicate ids.
2. Call `edge_mod.as_of(valid_at=p.as_of)` or `live_edges(...)`.
3. Filter by object if supplied.
4. If multiple live values exist for a `cardinality=many` predicate without object disambiguation, return `{multiple: true, candidates: [...]}`.
5. Reject if `edge.confidence < p.require_min_confidence`.
6. Enrich via `_shape_fact` with provenance and labels.

### 5.3 `graph_query` (`_graph_query` + [retrieval/graph.py](backend/app/retrieval/graph.py))

See §3.6. Recursive CTE with cycle guard, edge ACL injected into the join, optional predicate / type / temporal filters. `max_hops` default 2, `max_nodes` default 500.

### 5.4 `as_of_query` (`_as_of_query` in [tools.py:745-803](backend/app/api/mcp/tools.py#L745-L803))

Bi-temporal lookup. Calls `edge_mod.as_of(valid_at, sys_at)`:

```python
conditions.append("e.valid_time @> CAST(:valid_at AS timestamptz)")
if sys_at:
    conditions.append("e.sys_time @> CAST(:sys_at AS timestamptz)")
```

- **Valid-time only** — "what was true on date X" — returns all versions including closed ones whose `valid_time` contains the pin.
- **Both axes** — "what did we *believe* on `sys_at` about the world on `valid_at`" — pins both system and world time. Two `@>` checks against the two GiST-indexed tstzranges.

### 5.5 `get_provenance` ([domain/provenance.py](backend/app/domain/provenance.py))

Returns a W3C PROV-O JSON-LD document. Derivation chain via recursive CTE (depth-limited to 10):

```sql
WITH RECURSIVE walk AS (
  SELECT pad.upstream_activity_id AS id, 1 AS depth
  FROM prov_activity_derivation pad
  WHERE pad.derived_activity_id = :start
  UNION
  SELECT pad.upstream_activity_id, w.depth + 1
  FROM prov_activity_derivation pad
  JOIN walk w ON w.id = pad.derived_activity_id
  WHERE w.depth < :max_depth
)
```

Response shape (abbreviated):

```jsonc
{
  "@context": { "prov": "...", "dce": "..." },
  "@id": "dce:edge/<id>",
  "@type": ["Entity", "dce:Fact"],
  "dce:fact": "Alice works-at Acme",
  "dce:confidence": 0.95,
  "wasGeneratedBy": {
    "@id": "dce:activity/<id>",
    "dce:kind": "extraction",
    "wasAssociatedWith": { "@id": "dce:agent/llm/claude-haiku-4-5", "dce:agentKind": "llm" }
  },
  "wasDerivedFrom": [
    { "@id": "dce:episode/<id>", "dce:snippet": "..." },
    { "@id": "dce:activity/<upstream-id>", "dce:kind": "extraction" }
  ]
}
```

### 5.6 Vector / trigram / FTS plumbing

- **Vector** — operator `<=>` (cosine distance with `vector_cosine_ops`). Score returned as `1 - distance`. No explicit `ef_search` tuning — Postgres defaults.
- **Trigram** — `similarity(col, :q)` as a [0,1] score, plus ILIKE `%q%` fallback. GIN trigram indexes on canonical/aliases/fact.
- **FTS** — `plainto_tsquery('simple', :q)` against stored `block.search_tsv`. The `'simple'` config means no stemming, important for code/identifiers.

### 5.7 Setting the RLS context

[backend/app/db/session.py](backend/app/db/session.py) `session_scope()` runs at the start of each transaction:

```python
await session.execute(
    text("SELECT set_config(:k, :v, true)").bindparams(
        k='app.current_workspace_id', v=workspace_id))
```

`is_local=true` ties the setting to the transaction (survives pgbouncer transaction mode); `current_workspace_id()` reads it in every policy. Resolved by the FastAPI `current_principal` dependency from JWT `workspace_id` claim + optional `X-Workspace-Id` header, verified against `workspace_member`.

### 5.8 Provenance modal in the UI

[web/components/provenance/ProvenanceModal.tsx](web/components/provenance/ProvenanceModal.tsx) hits `GET /api/provenance/edge/{edge_id}`, which maps to `prov_mod.get_edge_provenance(session, edge_id)` ([backend/app/api/rest/provenance.py:21-30](backend/app/api/rest/provenance.py#L21-L30)). RLS auto-applies via the session dependency.

---

## 6. End-to-end walkthrough

To tie the layers together, here's the journey of a single fact: an agent reads a meeting transcript and learns "Alice now reports to Carla."

```
1. INGEST (agent)
   MCP tool: add_episode(content="Alice now reports to Carla. ...",
                         source_kind="meeting-transcript")
   → episode row inserted, content_embedding stored
   → processing_status='pending'
   → Arq job extract_episode(episode_id) enqueued

2. EXTRACT (worker)
   Load episode → LLM (Claude haiku, structured output) →
   {entities: [Alice, Carla],
    edges:   [(Alice, reports_to, Carla, confidence=0.92, valid_from=2026-05-18)]}

3. ENTITY RESOLUTION (per entity)
   Tier 1: lookup entity_external_ref / lower(canonical)
   Tier 2: pg_trgm similarity → top 50, threshold 0.9 / 0.3
   Tier 3 (only if 0.3 < score < 0.9): judge_pair() via LLM, cached in
           entity_resolution_decision

4. CONFIDENCE TRIAGE (propose_fact)
   relation_type "reports_to" has cardinality_object=one + high_stakes=true
   → contradictor finds existing edge (Alice, reports_to, Bob)
   → LLM contradictor judges "contradicts" with reasoning
   → BECAUSE high_stakes + cardinality_object=one + existing live edge:
     route to pending_fact(reason='high_stakes_contradiction')
     even though confidence 0.92 >= min_confidence

5. HUMAN REVIEW (web app)
   /review queue shows the pending row with the contradictor's reasoning
   Reviewer (editor+) clicks Approve →
     prov_activity(kind='approval', agent_kind='user', agent_ref=user_id)
     add_fact() runs the contradictor again under user auth
     (Alice, reports_to, Bob).sys_time upper closed at clock_timestamp()
     (Alice, reports_to, Bob).valid_time upper closed at 2026-05-18
     (Alice, reports_to, Carla) inserted as new live edge
     pending_fact.status='approved', approved_edge_id=new_edge.id
     audit_log row written

6. PROVENANCE LINK
   New edge.prov_activity_id → approval activity
   prov_activity_derivation(derived=approval, upstream=extraction)
   → chain: extraction (LLM) → approval (user) → edge

7. RETRIEVAL
   Later: search_memory(query="who does Alice report to")
   → 4 candidate streams run in parallel
   → RRF fuses, label policy filters (no labels here)
   → reranker (if enabled) re-scores
   → MMR diversifies
   → top hit: edge (Alice, reports_to, Carla) with confidence=0.92,
     freshness_days=0, derived_from=[approval, extraction]

8. AS-OF QUERY
   as_of_query(valid_at='2026-04-01') for (Alice, reports_to, ?)
   → SQL: WHERE valid_time @> '2026-04-01'::timestamptz
   → returns (Alice, reports_to, Bob) — the old fact that was true then
```

---

## 7. Honest limitations

A complete report names the gaps:

- **`entity.props` not DB-validated.** Pending `pg_jsonschema` ([init.sql:10](ops/postgres/init.sql#L10)). Pydantic at the boundary is the only schema check.
- **`workspace.high_sensitivity`** flag exists in the schema but enforcement is partial.
- **Ontology proposals** for new entity/relation types don't yet have a review queue equivalent to `pending_fact`; admins create types directly.
- **No SPARQL endpoint** — JSON-LD is output-side only. The platform emits PROV-O / OWL / RDFS / SKOS but doesn't accept SPARQL queries ([README.md:74](README.md#L74)).
- **Single embedding model.** 1536 dims hardcoded; swap requires column-alter migration.
- **MinIO holds exports only** — no large-file blob path for raw documents; episode content lives inline as jsonb.
- **License TBD** ([zep.md:71](docs/comparison/zep.md#L71)).
- **No automatic JSON-LD `@context` resolution** — context is inlined on every response.
- **Cycle detection in `prov_activity_derivation`** is by depth limit (10), backed by a CHECK that forbids self-loops; deeper cycles aren't structurally prevented.

---

## 8. Why these choices, in one line each

| Decision | One-line rationale |
|---|---|
| Postgres-only (no Neo4j) | One database, one backup story, one auth model, RLS for free. |
| Bi-temporal `tstzrange` + GiST | Two independent time axes queryable with `@>` containment. |
| Invalidate-never-delete | Audit trail of disagreements; as-of queries work without snapshots. |
| W3C PROV-O native | Existing ecosystem of validators / viewers; auditors recognize it. |
| Cross-agent `prov_activity_derivation` | Differentiator vs Graphiti — "which agent's output triggered this fact." |
| MCP as primary agent API | One protocol that Claude Desktop / Cursor / SDKs already speak. |
| RLS `ENABLE + FORCE` | A bug in app code cannot leak a cross-workspace row. |
| Sensitivity labels post-RLS in Python | New policies deployable without index changes; bypass for admin/service. |
| RRF over weighted-sum fusion | No cross-channel calibration; robust to scale differences. |
| ltree for type & label hierarchies | Single-column containment query (`@>`, `<@`) instead of recursive CTEs. |
| Confidence triage with thresholds | Three deterministic outcomes; humans only review the ambiguous band. |
| Contradictor only on high_stakes | LLM cost discipline; only the predicates that matter trigger it. |
| Yjs + Hocuspocus for editing | Real-time collab without inventing CRDT semantics. |
| Arq for workers | Lightweight Redis-backed queue; same Python codebase as the API. |

---

**End of report.**
