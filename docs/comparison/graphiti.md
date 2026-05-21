# Graphiti Adoption — Deep Comparison Report

**Question:** Could Dynamiq replace its custom pipeline with Graphiti? What would simplify, what would we sacrifice?

**TL;DR:** Graphiti is a strong, well-engineered library that does about **60% of what Dynamiq's write/read paths do** with significantly less code. Adopting it would eliminate the LLM-extraction pipeline, entity-resolution cascade, contradictor, hybrid-retrieval engine, and 8–10 weeks of custom code. The cost is **non-trivial**: ACL/RLS/labels, PROV-O provenance, the proposal queue, action system, and Postgres-only ops would all need to be **rebuilt on top of Graphiti** or abandoned. Graphiti is a memory engine; Dynamiq is a governed memory *platform*. The gap between those isn't small.

---

## 1. What Graphiti actually is (May 2026 state)

[Graphiti](https://github.com/getzep/graphiti) is an open-source temporal knowledge-graph library by Zep AI, published Apache 2.0 in January 2025, currently at ~45k GitHub stars. It's the kernel behind Zep Cloud's managed memory service. Production use cases: CRM agents, compliance pipelines, healthcare workflows.

**What it does:**

- Ingests **episodes** (text, JSON, or chat messages).
- Runs LLM extraction (Claude / GPT-4 / Gemini / Groq / Ollama) to produce typed entities and edges.
- Resolves duplicate entities via embedding + BM25 + MinHash/LSH + LLM.
- Stores facts with **four temporal dimensions** per edge: `created_at`, `valid_at`, `invalid_at`, `expired_at`.
- Handles contradictions by setting `invalid_at` on prior facts (invalidate, never delete).
- Hybrid search: semantic + BM25 + graph traversal, fused via Reciprocal Rank Fusion (RRF).
- Optional cross-encoder rerank and **center-node graph search** (re-rank by graph distance to a focal entity).
- Exposes ~5 tools via an official MCP server (added 2025).

**Storage backends:** Neo4j 5.26+ is default. Also supports FalkorDB (claims sub-10ms latency), Kuzu (embedded), Amazon Neptune + OpenSearch. FalkorDB Lite added recently for zero-config embedded deployments.

**Schemas:**

Entity node:
```
uuid, name, group_id, labels, summary, attributes (custom fields),
name_embedding (1024-dim), created_at
```

Edge (fact):
```
uuid, source_uuid, target_uuid, group_id, fact (LLM-generated text),
fact_embedding, created_at, valid_at, invalid_at, expired_at,
source_node_uuid (the episode that produced it)
```

Note the 1024 vs Dynamiq's 1536 dim — Graphiti uses its own embedding defaults.

**Multi-tenancy:** A `group_id` field on every node and edge. **All isolation is application-level filtering**: queries pass `group_id` as a parameter, and the layer above is responsible for not leaking. Hard isolation requires standing up a separate Neo4j instance per tenant.

**Agent surface:**

MCP tools shipped:
- `add_episode`
- `search_nodes`
- `search_facts`
- `delete_entity_edge`
- `delete_episode`

Plus REST/Python SDK. REST documentation has been flagged as incomplete (Issue #169).

**Performance signals:**
- Sub-10ms query latency on FalkorDB backend.
- P95 brought from 600ms → 150ms in late 2025 via Neo4j optimization.
- Demonstrated 10,000+ isolated tenant graphs in a single FalkorDB deployment.

**Published gaps (from their own issue tracker):**
- **Event-loop fragility** ([noted in production-readiness post](https://medium.com/@saeedhajebi/a-production-ready-api-for-graphitis-powerful-but-flawed-memory-15f17a9c1b41)) — Graphiti's async patterns conflict with orchestrators like Google ADK, requiring workarounds.
- **Temporal-correctness gaps** (Issue #1489, Feb 2026) — LLM extraction prompts contradict themselves on `invalid_at` handling; GPT guesses midnight UTC instead of using `REFERENCE_TIME`.
- **Text-only episodes** — no native PDF/image/audio ingestion path.
- **No metadata filtering beyond time** (Issue #436) — can't filter by arbitrary fields.
- **No custom extraction prompts** (Issue #1193) — extraction strategy is fixed.
- **No per-fact ACL** — by design.

---

## 2. Side-by-side: what each system does

| Capability | Dynamiq | Graphiti | Notes |
|---|---|---|---|
| **Bi-temporal model** | `valid_time` + `sys_time` as `tstzrange` with `@>` containment | `created_at` + `valid_at` + `invalid_at` + `expired_at` as point timestamps | Different shape — Dynamiq queries via range containment, Graphiti via timestamp comparisons |
| **Storage** | Postgres 17 (one DB) | Neo4j (or FalkorDB / Kuzu / Neptune) | Dynamiq: one DB. Graphiti: two systems if you want auth+app data + graph |
| **LLM extraction** | Custom pipeline, structured Pydantic output, ontology mode toggle | Decomposed multi-stage extraction with parallelizable sub-prompts | Graphiti's approach is more sophisticated (separable, testable steps) |
| **Entity resolution** | 3-tier: rules → trigram → LLM judge, cached in `entity_resolution_decision` | 2-pass: semantic+BM25 candidates → MinHash/LSH → LLM | Graphiti adds MinHash/LSH, more battle-tested |
| **Contradictor** | LLM judge fires only on `high_stakes` predicates, closes `valid_time` + `sys_time` | LLM-driven invalidation sets `invalid_at`, applies to all predicates | Dynamiq's is more controlled (cost discipline). Graphiti's is broader. |
| **Hybrid search** | RRF over 4 streams (vector, trigram, FTS, BM25 across entity/edge/episode/block) + optional cross-encoder + MMR | RRF over 3 streams (vector, BM25, graph traversal) + cross-encoder + center-node rerank | Roughly equivalent; Graphiti adds center-node rerank (genuinely nice feature) |
| **Graph traversal** | Recursive CTE with cycle guard, depth ≤ 2 default | Native Neo4j Cypher / FalkorDB queries | Graphiti wins on deep traversals |
| **Workspace isolation** | Postgres RLS, `ENABLE` + `FORCE` — DB-enforced, unbypassable | `group_id` filter at app layer — soft tenancy | **Critical difference** |
| **Per-fact ACL / labels** | `sensitivity_label` + `label_policy`, evaluated at retrieval | None | **Critical difference** |
| **RBAC** | `@require_workspace_role` decorators | None | **Critical difference** |
| **Provenance** | W3C PROV-O via `prov_activity` + `prov_activity_derivation`, cross-agent chains | `source_node_uuid` references episode only | **Critical difference** |
| **Standards output** | JSON-LD with `prov:` / `owl:` / `rdfs:` / `skos:` namespaces | Proprietary JSON | Trade-off, depends on consumer |
| **MCP server** | 22 tools (search, get_fact, add_episode, get_provenance, graph_query, as_of_query, assign_label, execute_action, propose/approve/reject_proposal, …) | 5 tools | Major coverage gap |
| **Confidence triage** | `extraction_policy` per type with `min_confidence` / `auto_reject_below` thresholds, `pending_fact` review queue | LLM-judged confidence per fact, no review queue | **Critical for governance** |
| **Approval workflow** | `propose_fact` → `pending_fact` → `approve_proposal` / `reject_proposal`, all audit-logged | None | **Critical difference** |
| **Kinetic actions** | `action_type` / `action_invocation` with idempotency, approval, side-effect declaration | None | Not Graphiti's domain |
| **Audit log** | `audit_log` table with actor_kind, target, diff, retention | Episode trail only | Different shape; episodes are the source-of-truth audit |
| **Block-level editor** | BlockNote + Yjs + Hocuspocus CRDT + `block.search_tsv` FTS | None | Different product scope |
| **Document model** | `document` + `block` + `block_entity_ref` for typed mentions inside prose | None | Not Graphiti's domain |
| **License** | TBD | Apache 2.0 | Graphiti is unambiguously OSS |
| **MIME support** | PDFs / images / text via playground content blocks | Text, JSON, messages only | Dynamiq handles richer ingestion |
| **Operational maturity** | Pre-1.0, single org | Production-tested at scale (10k+ tenants on FalkorDB), 45k stars | Graphiti has substantial real-world miles |

---

## 3. Simplifications we'd get

Concrete code paths Graphiti would replace, with rough magnitude:

### 3.1 The LLM extraction pipeline (~600 LOC saved)

[backend/app/extraction/pipeline.py](backend/app/extraction/pipeline.py) — the custom prompt, structured output, ontology-mode handling, embedding generation. Graphiti's parallelized multi-stage extraction is more sophisticated than ours. We'd drop:

- Custom extraction prompt + schema definition.
- Ontology auto-extension logic (`_extend_ontology`).
- LLM client wrapper for extraction.

**Risk:** Graphiti's extraction has known temporal-correctness issues (Issue #1489). We'd inherit those bugs. Our current pipeline is more controllable.

### 3.2 The entity-resolution cascade (~400 LOC saved)

[backend/app/domain/entity_resolver.py](backend/app/domain/entity_resolver.py) + [backend/app/llm/entity_resolver.py](backend/app/llm/entity_resolver.py). Graphiti's MinHash/LSH + 2-pass design is arguably better than our 3-tier trigram + LLM. We'd drop:

- `entity_external_ref` table, `entity_resolution_decision` cache, judge_pair() function.
- Cluster-too-large safeguard logic.

**Risk:** Lose external-ref-based resolution (email, wikidata Q-id, slug). Graphiti's resolver doesn't model these — it works on name + embedding + LLM judgment only. For our use case where external IDs matter (CRM, finance), this is a real regression.

### 3.3 The contradictor (~200 LOC saved)

[backend/app/llm/contradictor.py](backend/app/llm/contradictor.py). Graphiti's invalidation logic is built-in. We'd drop our high-stakes-only gate.

**Risk:** Graphiti runs contradictor logic on *all* predicates, not just high-stakes. Higher LLM cost. Less control over when it fires.

### 3.4 The hybrid retrieval engine (~700 LOC saved)

[backend/app/retrieval/hybrid.py](backend/app/retrieval/hybrid.py) + [backend/app/retrieval/graph.py](backend/app/retrieval/graph.py) + [backend/app/retrieval/rerank.py](backend/app/retrieval/rerank.py). Graphiti's `search()` does RRF + cross-encoder rerank + center-node rerank natively. We'd drop all of it.

**Risk:** Lose block-level FTS, lose query against the block tree, lose ability to scope by `entity_type` ltree hierarchy, lose MMR diversification. Center-node rerank is a nice feature we'd gain.

### 3.5 Embedding plumbing (smaller win)

Drop the `summary_embedding` / `fact_embedding` / `content_embedding` columns and HNSW indexes. Graphiti manages its own. Save the pgvector dependency.

**Risk:** Lock-in to Graphiti's embedding model (1024-dim vs our 1536-dim choice). Migration is irreversible without re-embedding.

### 3.6 The schema (~3 migrations could disappear)

If we go all-in on Graphiti, these become Graphiti's job:

- `entity`, `edge`, `entity_attribute`, `entity_external_ref`, `entity_resolution_decision`, `episode` — Graphiti's domain.
- The HNSW indexes, trigram indexes, GiST indexes, `pgvector` / `pg_trgm` / `btree_gist` extensions — only `ltree` would remain for ontology hierarchy (if we keep that).

### 3.7 Total estimated savings

| Component | LOC saved | Maintenance reduction |
|---|---|---|
| Extraction pipeline | ~600 | High (LLM prompt tuning) |
| Entity resolver | ~400 | High (resolution edge cases) |
| Contradictor | ~200 | Medium |
| Hybrid retrieval | ~700 | High (scoring/ranking tuning) |
| Schema migrations | ~500 lines of SQL | Medium |
| Embedding plumbing | ~150 | Low |
| **Total** | **~2,500 LOC + 500 SQL** | **Significant** |

For a small team, this is meaningful. Three core engineers freed from ongoing tuning of retrieval and extraction.

---

## 4. What we'd sacrifice

The honest cost. In order of impact.

### 4.1 Access control — the biggest sacrifice

You asked about this specifically. Three layers go away:

**Layer 1 — Postgres RLS:** Today every tenant table runs `ENABLE + FORCE ROW LEVEL SECURITY`. A bug in app code *cannot* leak rows across workspaces — the database refuses. Graphiti's `group_id` is an app-level filter on a Cypher query; if you forget the filter or write `WHERE group_id = $userInput` with a query-string injection, you have a breach. **The hard security floor disappears.**

**Layer 2 — RBAC decorators:** Today `@require_workspace_role("admin")` gates 30+ endpoints. None of this exists in Graphiti. We'd build it ourselves in the wrapping layer — fine, but it's work, and it's app-level (no defense in depth).

**Layer 3 — Sensitivity labels + policies:** Today `sensitivity_label` + `edge_label` + `label_policy` lets us mark facts `pii`, `confidential`, etc., and enforce "only admins see confidential" at retrieval. Graphiti has nothing like this. We could build it as a wrapping filter — but the labels would not be co-located with the facts; we'd maintain a parallel table in Postgres keyed by Graphiti's edge UUIDs. Fragile.

**Concrete implication:** For any customer in healthcare, finance, HR, regulated industries — the loss of per-fact ACL is a non-starter. We'd be regressing from "compliance-grade" to "soft tenancy."

### 4.2 Provenance — the second-biggest sacrifice

Graphiti tracks `source_node_uuid` per edge — that's it. It says "this fact came from episode X."

Dynamiq tracks:
- `prov_activity` per fact with `agent_kind` (`llm` / `user` / `system` / `connector`), `agent_ref` (model version), `agent_version` (for replay).
- `prov_activity_derivation` for **cross-agent chains** — "extraction activity → contradiction activity → approval activity → edge."
- W3C PROV-O JSON-LD output with `prov:wasGeneratedBy`, `prov:wasDerivedFrom`, `prov:wasAssociatedWith`.

Three things vanish if we adopt Graphiti unmodified:

1. **"Which model produced this fact?"** — Graphiti tracks the episode, not the LLM. Cannot answer "find every fact produced by claude-haiku-4-5 v20251001 for re-evaluation."
2. **Cross-agent lineage** — Graphiti has no `wasDerivedFrom` between activities. The chain "user-uploaded-document → extraction → contradictor → approval → edge" collapses to "this fact came from this episode."
3. **PROV-O standard output** — Graphiti emits its own JSON shape. Auditors with standard PROV tools can't load it directly.

**Concrete implication:** Audit-grade provenance, which is one of Dynamiq's core differentiators, is gone unless we shadow-track everything in a side table.

### 4.3 The proposal / review queue

Dynamiq's `pending_fact` + `extraction_policy` (per-type confidence thresholds, `min_confidence` / `auto_reject_below`) + `propose_proposal` / `approve_proposal` / `reject_proposal` workflow has **no Graphiti equivalent**. Graphiti commits every extracted fact to the live graph immediately (modulo confidence-based filtering inside the LLM judge).

Use cases this breaks:
- Compliance review before facts enter the graph.
- Human-in-the-loop curation of low-confidence extractions.
- Audit trail of "what was proposed but rejected."

To rebuild: shadow `pending_fact` table in Postgres, intercept Graphiti's writes via a wrapper that routes through Pydantic + thresholds, then write to Graphiti after approval. **Possible, but adds back complexity we just removed.**

### 4.4 Postgres-only operational story

Two databases instead of one:

| Operation | Today | With Graphiti |
|---|---|---|
| Backup | One Postgres backup | Postgres + Neo4j (or FalkorDB) backups |
| Point-in-time recovery | WAL replay | WAL replay + graph DB-specific recovery |
| Auth & schema migrations | Alembic | Alembic + Graphiti's schema management |
| Monitoring | One DB | Two DBs |
| HA | Postgres replication | Postgres replication + Neo4j cluster |
| Cost | One Postgres instance | Postgres + Neo4j (or FalkorDB) |
| Connection pooling | pgbouncer | pgbouncer + graph DB pooler |

For a small team, **doubling the infrastructure footprint is real cost**. FalkorDB Lite (embedded) mitigates this for dev/small deployments, but production usually wants the standalone graph DB for performance.

### 4.5 Bi-temporal semantics

Graphiti's 4-field model (`created_at`, `valid_at`, `invalid_at`, `expired_at`) is **not** equivalent to Dynamiq's `tstzrange` model. Two concrete differences:

1. Graphiti uses point timestamps. Dynamiq's ranges support `@>` containment queries — "what was true on date X" is a single GiST-indexed predicate. With Graphiti's model, the same query is two timestamp comparisons (`valid_at <= X AND (invalid_at IS NULL OR invalid_at > X)`), which is fine but lacks the algebra of range types.
2. Dynamiq's `sys_time` is also a range, enabling "what did we *believe* on date X about the world on date Y" with two `@>` checks. Graphiti tracks `created_at` (when ingested) and `expired_at` (internal versioning) but the semantics are different — system-time queries against Graphiti would require different SQL.

**Concrete implication:** Custom queries that use range algebra would need rewriting. Not a blocker but a real migration cost.

### 4.6 17 of 22 MCP tools

Graphiti's MCP server exposes 5 tools. Dynamiq's exposes 22. The missing 17:

- `get_fact` (decision-support shortcut with object disambiguation)
- `as_of_query` (explicit bi-temporal)
- `get_provenance` (PROV-O JSON-LD)
- `graph_query` (bounded traversal with predicate/type filters)
- `invalidate_fact` (explicit invalidation with reason)
- `update_entity` (canonical/alias/props update)
- `ontology_describe`, `create_entity_type`, `create_relation_type`, `propose_ontology` (ontology management)
- `list_proposals`, `approve_proposal`, `reject_proposal` (review queue)
- `list_labels`, `assign_label` (sensitivity)
- `list_action_types`, `execute_action`, `list_action_invocations` (kinetic actions)

We'd build all of these as wrappers around Graphiti's primitives. **Wrapping ≠ free** — each tool needs Pydantic schemas, error handling, audit logging, RBAC. Realistic estimate: 2–3 person-weeks of work.

### 4.7 The action system

`action_type` (input JSON Schema, required role, idempotency, approval) + `action_invocation` (per-execution rows with `prov_activity_id`, `emitted_edge_id`). Graphiti has nothing here. This is Dynamiq's "kinetic" write-back path — facts that *do something* in the world (send a message, post to Slack, write to a CRM).

If actions matter for your roadmap, this stays Dynamiq-side regardless.

### 4.8 The document model

`document` (Yjs CRDT state) + `block` (hierarchical block tree with FTS) + `block_entity_ref` (entity mentions). Graphiti's episode model is closer to a chat-message log; it has no concept of structured prose documents with entity references. The web app's block editor would still need to be backed by Postgres regardless.

### 4.9 Standards interop

Graphiti emits its own JSON. We lose:
- JSON-LD output via `Accept: application/ld+json`.
- `prov:` / `owl:` / `rdfs:` / `skos:` vocabulary mapping.
- `owl:sameAs` for entity reconciliation against external knowledge bases (Wikidata, etc.).

If your buyer is a research lab or enterprise with a SPARQL endpoint, this matters. For typical SaaS buyers, less so.

### 4.10 Known Graphiti production issues we'd inherit

From the research:
- **Event-loop fragility** in async orchestrators. Some users report "Event loop is closed" errors when integrating with Google ADK or similar. Workarounds exist but are not standard.
- **Temporal correctness gaps** (Issue #1489, Feb 2026). LLM extraction sometimes guesses midnight UTC instead of using REFERENCE_TIME. This is an active bug.
- **No custom extraction prompts** (Issue #1193). Cannot tune the extractor for domain-specific terminology without forking.
- **REST API docs lag the Python SDK** (Issue #169).

These are tractable but they'd land in our lap.

---

## 5. Migration sketch — what would adoption look like?

If we went for it, the architecture would land somewhere like:

```
                    Agents (MCP) & Web app
                          │
              ┌───────────▼───────────┐
              │   FastAPI wrapper     │
              │   (Pydantic, RBAC,    │
              │   provenance shadow,  │
              │   labels, proposals)  │
              └─────┬─────────────┬───┘
                    │             │
        ┌───────────▼───┐   ┌────▼────────────┐
        │   Postgres    │   │    Graphiti     │
        │ (users, auth, │   │  (entities,     │
        │  documents,   │   │   edges,        │
        │  labels,      │   │   episodes,     │
        │  proposals,   │   │   embeddings)   │
        │  prov shadow, │   │                 │
        │  actions,     │   └─────────────────┘
        │  audit_log)   │           │
        └───────────────┘    Neo4j or FalkorDB
```

**Three things stay in Postgres regardless:**

1. **Auth, workspaces, members, agent tokens** — Graphiti has no opinion here.
2. **Documents, blocks, Yjs CRDT state** — Graphiti's episode model doesn't fit.
3. **Governance shadow** — sensitivity labels, label policies, proposal queue, action types and invocations, audit log, PROV-O activity rows. All keyed by Graphiti's UUIDs.

**Two things move to Graphiti:**

1. Entity / edge storage with bi-temporal model.
2. Extraction + resolution + retrieval pipelines.

**One critical wrapper layer** sits between agents and Graphiti to enforce:
- Workspace isolation (group_id filter).
- RBAC.
- Label-policy filtering on retrieval results.
- Proposal queue interception before facts hit the graph.
- Provenance shadow-writes for every Graphiti operation.

That wrapper is **the work**. Estimated effort:

| Phase | Estimate |
|---|---|
| Stand up Neo4j or FalkorDB, ops/backup setup | 1 week |
| Replace extraction pipeline with Graphiti's `add_episode` | 1 week |
| Replace retrieval with Graphiti's `search()`, port the 17 missing MCP tools | 3 weeks |
| Build governance wrapper (RBAC, labels, proposals, provenance shadow) | 4 weeks |
| Data migration from Postgres → Graphiti | 2 weeks |
| Re-test, fix edge cases, performance tuning | 2 weeks |
| **Total** | **~13 person-weeks** |

Less if you cut corners on governance (acceptable for new dev, regressive for existing customers).

---

## 6. Decision framework

Use this matrix to decide:

| If you... | Recommendation |
|---|---|
| Are pre-customer, optimizing for time-to-MVP, no regulated buyer in pipeline | **Adopt Graphiti.** Save the engineering effort. Build governance later if needed. |
| Are pre-customer but explicitly targeting healthcare / finance / HR / regulated | **Don't adopt.** ACL/RLS/audit are table stakes for those buyers. |
| Have shipped customers using sensitivity labels, proposals, or PROV-O | **Don't adopt** without a major migration plan. Customers would regress. |
| Care about Postgres-only ops as a hard constraint (single ops team, no graph-DB experience) | **Don't adopt.** Neo4j ops is its own discipline. |
| Want deep multi-hop graph traversals (5+ hops, complex path constraints) | **Lean toward Graphiti.** Cypher beats recursive CTEs for that workload. |
| Need MCP-native agents (Claude Desktop / Cursor / agent SDKs as primary surface) | **Hybrid.** Use Graphiti for the kernel, wrap with our MCP tool set. |
| Need to interop with SPARQL endpoints or PROV-aware tooling | **Don't adopt** unmodified. JSON-LD + PROV-O are Dynamiq differentiators. |

---

## 7. Recommendation

**Don't fully adopt Graphiti. Consider it for the kernel only.**

Reasoning:

1. **The ACL/label/proposal stack is the product.** "Agent memory" as a category is crowded — Graphiti, Mem0, Memori, Cognee. What makes Dynamiq distinct is *governed* agent memory: RLS, labels, proposals, PROV-O. Replacing the storage kernel with Graphiti doesn't change that thesis, but you lose half of it in the process unless you carefully rebuild on top.

2. **The "simplification" is partly an illusion.** You'd remove 2,500 LOC of pipeline code, then add ~1,500 LOC of wrapper code to restore the lost governance. Net win is real but smaller than it looks.

3. **Operational doubling is a real cost for a small team.** Two databases means two backup strategies, two HA stories, two sets of dashboards. Even FalkorDB Lite doesn't fully escape this for production deployments.

4. **Graphiti's known issues land in our lap.** Event-loop fragility, temporal correctness bugs, locked extraction prompts. We currently control all of these.

**However:**

There's a real argument for **Graphiti-as-retrieval-engine, not as storage**. Specifically:

- Keep all data in Postgres (unchanged).
- Use Graphiti **only** for the hybrid retrieval + center-node rerank, ingesting from our Postgres rows on a schedule or via streaming.
- Get the retrieval quality benefits without the storage migration cost.

This is sometimes called the **read-side cache** pattern. Worth a spike: stand up Graphiti pointed at FalkorDB, sync edges/entities/episodes to it, see if retrieval quality measurably improves on our test set. If yes, keep both. If no, drop Graphiti.

**Verdict:** The full migration is **not worth it**. The selective adoption (retrieval only, or Graphiti for new greenfield projects without our governance requirements) is **worth a 2-week spike to validate**.

---

## 8. Open questions to resolve before any migration

1. **Customer roadmap.** Are any sold or near-sold customers in regulated industries (healthcare, finance, HR)? If yes → governance is non-negotiable → don't adopt.
2. **License resolution.** Dynamiq's license is currently TBD. If we plan to ship as Apache 2.0 ourselves, Graphiti is license-compatible. If we plan commercial → check Apache 2.0 obligations.
3. **Retrieval-quality benchmark.** Set up a test set (queries + expected entity/fact hits) and measure Dynamiq's current hybrid retrieval vs Graphiti's on the same data. The 18.5% accuracy claim in Graphiti's paper is vs MemGPT, not vs our pipeline.
4. **Neo4j vs FalkorDB.** If we did move kernel, FalkorDB's sub-10ms claim is attractive but it's a younger product. Neo4j's operational story is more mature.
5. **PROV-O customer demand.** Has any customer or prospect actually asked for PROV-O / JSON-LD / SPARQL interop? If no, the standards differentiator is theoretical and giving it up costs less.

Answer these before committing engineering weeks to a migration.

---

**End of report.**
