# Dynamiq Context Engine

A self-hostable memory platform that **edits like Notion/Obsidian** for humans and **serves AI agents like Zep/Mem0** — sharing one typed ontology, bi-temporal knowledge graph, and single Postgres database.

---

## Why this exists

Knowledge tools today split into two camps:

- **Human-facing KM** (Notion, Obsidian, Roam) — excellent block-based editing UX, backlinks, graph views. But they have no first-class agent story; anything an LLM writes is a second-class attachment.
- **Agent-memory SDKs** (Zep/Graphiti, Mem0, Memori, A-MEM) — rich semantic memory with temporality and contradiction handling. But humans can't naturally read, let alone edit, the graph.

Both sides pay for the gap. Humans can't trust what the agent wrote because they can't see it in place. Agents can't trust what humans wrote because the schema drifted without telling them.

This project collapses the two into one store with one ontology. Every edit — human keystroke, agent tool call, ingested episode — lands in the same bi-temporal graph with the same provenance and audit trail. Humans edit via a BlockNote doc; agents write via MCP tools. Both surfaces read and extend the same typed schema.

---

## Highlights

- **Bi-temporal graph.** Every edge carries `valid_time` (when it's true in the world) and `sys_time` (when the system believes it). Invalidate, never delete. `as_of(valid_time, sys_time)` is a first-class query.
- **Shared ontology.** Typed entities and relations with JSON-Schema validation, subtype hierarchy via `ltree`, inverse/symmetric/transitive flags, cardinality enforcement, `owl:sameAs`-style entity merge.
- **Agent-driven ontology creation.** AI agents (and humans) create new types. The `propose_ontology` MCP tool analyses text and proposes a full domain ontology that can be previewed or auto-applied.
- **Flexible / auto ontology modes.** Per workspace: extraction must stick to existing types (`strict`), can extend when needed (`flexible`), or is free to invent (`auto`).
- **Collaborative block editor.** BlockNote on TipTap, Yjs realtime sync via Hocuspocus. Typed `@mention` inline content resolves entities from the graph. Backlinks rebuild on every save.
- **Graph view.** Sigma.js + graphology with ForceAtlas2 in a Web Worker. Type/predicate filters plus a bi-temporal "as of" time slider.
- **Hybrid retrieval.** pgvector HNSW + tsvector BM25-style + pg_trgm fuzzy, fused with RRF and diversified with MMR. Optional 1-hop graph expansion.
- **Extraction pipeline.** Async LLM extractor (LiteLLM) produces entities + bi-temporal edges from raw episodes; contradictor closes prior facts on high-stakes predicates.
- **MCP server.** 12 tools: `search_memory`, `get_entity`, `graph_query`, `add_fact`, `invalidate_fact`, `add_episode`, `update_entity`, `ontology_describe`, `create_entity_type`, `create_relation_type`, `propose_ontology`, `as_of_query`. Exposed via REST and JSON-RPC (Claude Desktop / Cursor compatible).
- **Multi-tenant by construction.** Every table scoped by `workspace_id` with forced RLS; FastAPI runs `SET LOCAL app.current_workspace_id` inside every transaction.
- **Self-hosted.** A single `docker compose up` brings Postgres 17 + FastAPI + Arq workers + Next.js + Hocuspocus + Redis + MinIO + Caddy.

---

## Inspiration

Named prior art that shaped this codebase. Read these first if you want to understand the tradeoff space.

**Agent memory systems**

- **[Zep / Graphiti](https://github.com/getzep/graphiti)** — bi-temporal edges (`valid_time` + `sys_time`), write-time contradictor on high-stakes facts. Direct model for the edge module.
- **[Mem0](https://github.com/mem0ai/mem0)** — LLM-as-memory-controller with a small op set (`add` / `update` / `delete` / `noop`). We keep the pattern; replace `delete` with `invalidate`.
- **[Memori](https://github.com/GibsonAI/memori)** — "conscious-ingest" promotion (short-term → long-term after repeated retrieval). Roadmap item.
- **[A-MEM](https://arxiv.org/abs/2502.12110)** — agentic memory evolution (merging, summarizing, decay). Roadmap item.
- **[HippoRAG](https://arxiv.org/abs/2405.14831)** — personalized PageRank over entity graph + synonym edges for retrieval. Roadmap item.
- **[Cognee](https://github.com/topoteretes/cognee)** — RDF + graph + vector lakehouse. We stop at ~40% up the semantic-web stack; Cognee goes further into SHACL and reasoning.
- **[Letta (formerly MemGPT)](https://github.com/letta-ai/letta)** — procedural memory + tool-call conventions. We name MCP tools close to Letta's for LLM familiarity.

**Human-facing KM**

- **[Notion](https://www.notion.so)** — block model; we use BlockNote for fidelity.
- **[Obsidian](https://obsidian.md)** — graph view; backlinks; local-first philosophy. We're self-hosted rather than local-first, but the graph UX is directly inspired.
- **[Roam Research](https://roamresearch.com)** — bi-directional linking; daily notes. Our `block_entity_ref` rebuild on save is Roam-style.

**Editor stack**

- **[BlockNote](https://www.blocknotejs.org)** on **[TipTap](https://tiptap.dev)** + **[ProseMirror](https://prosemirror.net)** — block editor with React inline-content hooks.
- **[Yjs](https://yjs.dev)** + **[Hocuspocus](https://tiptap.dev/docs/hocuspocus/introduction)** — CRDT realtime collab.

**Graph viz**

- **[Sigma.js](https://www.sigmajs.org)** + **[graphology](https://graphology.github.io)** — WebGL graph rendering with ForceAtlas2 in a Web Worker.

**Agent protocol**

- **[Model Context Protocol (MCP)](https://modelcontextprotocol.io)** — Anthropic's open tool-calling spec. Our MCP server speaks both SSE and JSON-RPC.

---

## Standards honored

- **Bi-temporal databases.** Snodgrass's *Developing Time-Oriented Database Applications in SQL* (1999) is the reference; SQL:2011 added application-time + system-versioned rows. We implement both axes with `tstzrange` + GiST indexes rather than SQL:2011 period columns (better flexibility for asymmetric window queries).
- **Semantic web (at 40% up the stack).** We honor the idea of typed entities and relations with class hierarchy, inverse/symmetric/transitive flags, and `owl:sameAs`-style merge, but we stop short of full OWL DL reasoning or a triple store. See the [OWL 2 Profiles spec](https://www.w3.org/TR/owl2-profiles/) — we live between RDFS-Plus and OWL 2 RL.
- **[SHACL](https://www.w3.org/TR/shacl/)** for shape constraints. We compile a small YAML DSL ("SHACL-lite") to Pydantic validators. Optional `pyshacl` pass for users who author real Turtle.
- **[JSON-LD](https://www.w3.org/TR/json-ld11/)** at the API boundary — `GET /entities/{id}?format=jsonld` emits [schema.org](https://schema.org)-aligned JSON-LD. Free interop with other KGs.
- **[JSON Schema](https://json-schema.org) Draft 2020-12** — one schema, three places: `pg_jsonschema` CHECK constraint at the DB, `jsonschema` Python at the API, [`@rjsf/core`](https://github.com/rjsf-team/react-jsonschema-form) in the UI.
- **[MCP](https://modelcontextprotocol.io/specification)** — JSON-RPC tool surface; REST equivalent at `/api/mcp/tools` for debugging.
- **PostgreSQL extensions.** [pgvector](https://github.com/pgvector/pgvector) HNSW cosine; `tsvector` + GIN for BM25-style FTS; [pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html) for fuzzy; [`ltree`](https://www.postgresql.org/docs/current/ltree.html) for subtype hierarchy; `btree_gist` for range + equality joins; `citext` for case-insensitive email; `pgcrypto` for UUIDs.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| DB | **PostgreSQL 17** | Single source of truth. Extensions cover graph, vector, FTS, range. No AGE, no separate triple store. |
| Backend | **Python 3.12 + FastAPI** | Typed async REST + MCP + Arq workers in one codebase. |
| Web | **Next.js 15 + shadcn + BlockNote** | App Router + React 19 + Tailwind. BlockNote is the closest open-source Notion-fidelity editor. |
| Collab | **Hocuspocus (Node + TS)** | BlockNote's Yjs integration is Node-native; smallest possible sidecar. |
| Queue | **Redis 7** | Arq job queue + cache + LISTEN/NOTIFY fanout. |
| Storage | **MinIO** | S3-compatible; attachments stay portable. |
| Routing | **Caddy** | TLS + per-path reverse proxy in ~20 lines of Caddyfile. |
| Auth | **BetterAuth** | Next.js-native; shares HS256 JWT with FastAPI via `JWT_SECRET`. |
| LLM | **LiteLLM** | Provider abstraction; defaults to `claude-sonnet-4-6` for extraction and contradictor, `text-embedding-3-small` for embeddings. |

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ Next.js 15 (App Router) + shadcn + BlockNote                       │
│   Block editor · Typed @mention · Ontology-driven forms            │
│   Sigma.js graph view · Ontology editor · Agent console            │
│   BetterAuth signup/login · Dark + light themes                    │
└────────────────────────────────────────────────────────────────────┘
     │ REST (typed via openapi-typescript)    ▲ WebSocket (LISTEN/NOTIFY)
     ▼                                         │
┌───────────────────────────────────┐  ┌────────────────────────────┐
│ FastAPI (Python 3.12)             │  │ Hocuspocus (Node + TS)     │
│   REST · MCP (SSE + JSON-RPC)     │  │   Yjs collab for blocks    │
│   Hybrid retrieval (RRF + MMR)    │  │   Persists Yjs blob +      │
│   Bi-temporal edge manager        │  │   projected block tree     │
│   Extraction workers (Arq/Redis)  │  │                            │
│   JWT verify → RLS SET LOCAL      │  │                            │
└───────────────────────────────────┘  └────────────────────────────┘
     │ SQL  ▲ LISTEN/NOTIFY                    │
     ▼      │                                  │
┌────────────────────────────────────────────────────────────────────┐
│ PostgreSQL 17                                                      │
│   pgvector (HNSW) · tsvector/GIN · pg_trgm                         │
│   ltree · tstzrange + btree_gist · citext · pgcrypto               │
│   Row-level security (workspace scoping, forced)                   │
└────────────────────────────────────────────────────────────────────┘
     │
┌────────────────────────────────────────────────────────────────────┐
│ Redis 7 (Arq queue, cache) · MinIO (S3-compat attachments)         │
│ Caddy (TLS + routing)                                              │
└────────────────────────────────────────────────────────────────────┘
```

Service boundaries:

- **FastAPI** owns the hard logic: ontology validation, extraction, retrieval, MCP, bi-temporal edges.
- **Next.js** handles editing UX and renders server-fetched graph/entity state.
- **Hocuspocus** is a tiny Node service because BlockNote's Yjs integration is Node-native. Persists both the Yjs binary (wire format) and a normalized block tree (queryable SQL).
- **Postgres** is the only source of truth. Redis and MinIO are operational supports.

---

## Quickstart

```bash
cp .env.example .env
# At minimum set:
#   JWT_SECRET=<long random string>
#   BETTER_AUTH_SECRET=<long random string>
# Optional (graceful degrade without them):
#   ANTHROPIC_API_KEY=sk-ant-...     (extraction, contradictor, propose-ontology)
#   OPENAI_API_KEY=sk-...            (embeddings)

docker compose up --build
```

First-boot is fully automatic: the backend entrypoint runs `alembic upgrade head`, which creates the entire schema (platform tables + BetterAuth `user/session/account/verification`) before uvicorn starts.

**Default host ports** (from `docker-compose.yml`):

| Service | Port |
|---|---|
| Web UI | `:3000` |
| Backend | `:8000` |
| Hocuspocus | `:1234` |
| Postgres | `:5432` |
| Redis | `:6379` |
| MinIO API | `:9000` |
| MinIO console | `:9001` |
| Caddy (all-in-one) | `:80` |

If these clash with other local apps, create a `docker-compose.override.yml` (gitignored) to remap host ports.

## Endpoints

- `http://localhost:3000` — Web UI (sign up, create workspace, edit)
- `http://localhost:8000/docs` — FastAPI OpenAPI
- `http://localhost:8000/api/mcp/rpc` — MCP JSON-RPC for external agents
- `http://localhost:8000/api/mcp/tools` — REST tool catalog
- `http://localhost:9001` — MinIO console (`memoryminio` / `memoryminio`)
- `ws://localhost:1234/collab` — Hocuspocus

---

## Layout

```
backend/             FastAPI + Arq workers + MCP server (Python 3.12)
  app/api/rest       REST endpoints
  app/api/mcp        MCP server (REST + JSON-RPC, 12 tools)
  app/api/websocket  WS event stream backed by pg LISTEN/NOTIFY
  app/domain         entity, edge (bi-temporal), ontology, document, episode,
                     auto-ontology, workspace
  app/retrieval      hybrid search + n-hop graph traversal
  app/extraction     LLM extractor pipeline (episode → entities + edges)
  app/llm            LiteLLM provider, embedding, contradictor
  app/workers        Arq jobs (extract, propose-and-apply)
  app/db/migrations  Alembic (schema + triggers + BetterAuth tables)
  tests              pytest: bi-temporal invariants, ontology, entity, mcp,
                     full REST end-to-end
  Dockerfile + docker-entrypoint.sh

web/                 Next.js 15 app (TypeScript strict)
  app/               App Router (auth, onboarding, per-workspace pages)
  components/        app-shell, editor (BlockNote+Yjs), entity, graph,
                     ontology, agent, ui (shadcn primitives)
  lib/               typed API client, auth-client, workspace context,
                     providers (React Query, ThemeProvider, Toast, Workspace)
  e2e/               Playwright smoke
  vitest.config.ts   Component-level regression tests

collab/              Hocuspocus + Yjs-to-block-tree projection (Node TS)

seeds/ontology.yaml  Built-in 13 entity types + 15 relation types

ops/                 Postgres init SQL + Caddyfile

.github/workflows/   CI (web: format:check → lint → typecheck → test → build)
.husky/              pre-commit hook (web lint-staged + typecheck + test)
```

---

## Built-in ontology

Every new workspace seeds with ([`seeds/ontology.yaml`](seeds/ontology.yaml)):

**Entity types (13)** — abstract roots `thing` · `agent` · `work` · `content` · `concept`, plus concrete `person`, `organization`, `project`, `task`, `meeting`, `document`, `note`, `topic`.

**Relation types (15)** — `works_at`, `member_of`, `manages`, `assigned_to`, `part_of`, `depends_on`, `attended`, `authored`, `mentions`, `references`, `tagged`, `follows`, `related_to`, `knows`, `located_at`.

Users and agents can freely extend the ontology in place, either by hand in the ontology editor or by calling the `propose_ontology` / `create_entity_type` / `create_relation_type` MCP tools.

---

## Testing

One-shot web gate (format + lint + typecheck + vitest):

```bash
docker compose exec -T web pnpm check
```

Backend:

```bash
docker compose exec -T backend pytest
docker compose exec -T backend ruff check .
```

Playwright smoke (requires the stack running):

```bash
docker compose exec -T web pnpm exec playwright test
```

CI mirror (same commands, against an ephemeral pnpm cache): `.github/workflows/web-ci.yml`.

---

## Roadmap (v1.1+)

- Cross-encoder rerank after RRF (HippoRAG-style).
- Personalized PageRank (PPR) over the entity graph; synonym edges for retrieval.
- Oxigraph read-side sidecar projecting the property graph to N-Quads for SPARQL queries — for users who need triple-pattern matching.
- [A-MEM](https://arxiv.org/abs/2502.12110)-style memory evolution: merge, summarize, and decay episodic memories.
- MemoryBank-style access-frequency decay on the semantic layer.
- Bases-style inline query blocks in documents (Obsidian / Notion 3.0 direction).
- Full [Conscious Ingest](https://github.com/GibsonAI/memori) — short-term → long-term promotion after repeated retrieval (Memori).
- Advanced SHACL import/export (beyond SHACL-lite YAML).

---

## Connecting agents

External AI agents consume this workspace through the MCP server at
`${PUBLIC_BASE_URL}/api/mcp/rpc`. Open `/[workspace]/settings/integrations`
in the web UI, mint a token, then paste the shown snippet into your client.

- **Claude Code** — `claude mcp add-json memory '{"type":"http","url":"…","headers":{"Authorization":"Bearer mem_…"}}' --scope user`. Tools appear under `/mcp`.
- **Cursor** — drop the JSON block into `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project).
- **Claude Desktop** — edit `claude_desktop_config.json`.

Tokens are workspace-scoped, revocable, and argon2-hashed at rest. Discovery metadata is at `/.well-known/oauth-protected-resource` (RFC 9728); the server advertises itself as `protocolVersion: 2025-06-18`.

## Contributing

See [`AGENTS.md`](AGENTS.md) — the onboarding doc for humans and coding agents. It covers the mental model, standing non-negotiables, the landmines we've paid for, and task recipes for common operations.

---

## License

TBD. Contact the maintainer before redistributing or relying on this in production.
