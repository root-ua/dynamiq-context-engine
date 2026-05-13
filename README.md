# Dynamiq Context Engine

A self-hostable, **agent-first** memory platform: typed bi-temporal
knowledge graph + W3C PROV-O provenance + an MCP server, sharing one
Postgres database with a human-facing Notion/Obsidian-style editor.

Humans edit blocks in the web app. Agents (Claude Code, Cursor, custom
Claude / ChatGPT clients) read and write through the MCP server.
Everything lands in the same store with the same audit trail.

---

## Quick start

```bash
git clone <repo> && cd memory-experiments
cp .env.example .env
# Fill in JWT_SECRET, BETTER_AUTH_SECRET, HYDRATE_SECRET (any random
# 32-byte hex), plus ANTHROPIC_API_KEY if you want extraction /
# playground / live tests.

make up                              # docker compose up --build
open http://localhost:3000           # signup → workspace → playground
```

That's it. First boot pulls Postgres 17 (pgvector), Redis 7, a pinned
MinIO release, runs the Alembic migration container to head, and
brings the backend / worker / hocuspocus / web on line.

---

## What this is, in 30 seconds

- **A typed bi-temporal property graph in Postgres.** Every edge
  carries `valid_time` and `sys_time` as `tstzrange` columns; invalidate,
  never delete; `as_of(valid_time, sys_time)` is one query.
- **Full PROV-O provenance.** Every fact links to the activity that
  produced it and the agent (LLM / user / system) that ran the
  activity. Cross-agent `wasDerivedFrom` chains are first-class.
- **An MCP server (22 tools).** Agents read and write through
  `search_memory`, `get_fact`, `add_fact`, `add_episode`,
  `get_provenance`, `graph_query`, `as_of_query`, sensitivity-label
  governance, kinetic-action invocation, and more.
- **Sensitivity labels + policy on top of workspace RLS.** Per-fact
  ACL plus policies like "PII and Public are mutually exclusive →
  drop on retrieval" — admins bypass, editors get filtered.
- **A chat playground.** Open `/playground` and watch a real Claude
  agent stream tool calls against your workspace.

What this is **not**: a connector platform. Ingestion is the calling
agent's job (Claude Code with file-system access, custom Drive /
Notion / Jira tooling). The platform stops where the graph starts. See
[`docs/architecture/rfc-001-alignment.md`](docs/architecture/rfc-001-alignment.md)
for the rationale.

---

## How it compares

A two-line summary lives at
[`docs/comparison/README.md`](docs/comparison/README.md):

| | Dynamiq | Zep / Graphiti | Mem0 | Memori | Cognee |
|---|---|---|---|---|---|
| Bi-temporal `tstzrange` | ✅ | ✅ | partial | – | – |
| W3C PROV-O on every fact | ✅ | – | – | – | partial |
| Per-fact sensitivity labels | ✅ | – | – | – | – |
| Embedded human editor | ✅ | – | – | – | – |
| Triple store / SPARQL | ❌ (JSON-LD only) | – | – | – | ✅ |
| RAG / chunking pipeline | external | – | partial | – | ✅ |

Long-form comparisons:
[`zep.md`](docs/comparison/zep.md) ·
[`mem0.md`](docs/comparison/mem0.md) ·
[`memori.md`](docs/comparison/memori.md) ·
[`cognee.md`](docs/comparison/cognee.md).

---

## Skills

Drop the `skills/` folder into your Claude Code config to teach it
how to use the MCP surface effectively. Each file is one capability:

- [`querying-with-confidence`](skills/querying-with-confidence/SKILL.md) — when to pick `get_fact` over `search_memory`.
- [`ingesting-facts`](skills/ingesting-facts/SKILL.md) — `add_episode` then propose_fact vs direct `add_fact`.
- [`agent-to-agent-provenance`](skills/agent-to-agent-provenance/SKILL.md) — chain `derived_from_activity_ids`.
- [`governance-labels`](skills/governance-labels/SKILL.md) — when to assign `pii`, `public`, custom labels.
- [`action-invocation`](skills/action-invocation/SKILL.md) — invoking kinetic actions with approval.
- [`time-travel-queries`](skills/time-travel-queries/SKILL.md) — `as_of_query` patterns.
- [`reviewing-pending-facts`](skills/reviewing-pending-facts/SKILL.md) — the proposals workflow.

See [`skills/README.md`](skills/README.md) for installation.

---

## What's in this repo

```
backend/                FastAPI + Arq workers + MCP server (Python 3.12)
  app/api/rest          REST endpoints (entities, edges, episodes,
                        documents, search, graph, ontology, proposals,
                        provenance, labels, actions, exports, playground)
  app/api/mcp           MCP tool surface (22 tools)
  app/domain            entity, edge (bi-temporal), ontology, action,
                        sensitivity, proposals, provenance, workspace
  app/retrieval         hybrid (RRF + MMR + label-policy) + graph traversal
  app/extraction        LLM extractor (episode → entities + edges)
  app/jsonld            JSON-LD serialisation at the API boundary
  app/llm               LiteLLM provider, embedding, contradictor
  app/workers           Arq jobs (extract, propose-and-apply, exports)
  app/db/migrations     Alembic migrations
  tests                 pytest (unit, scenario, opt-in live_llm)
  Dockerfile

web/                    Next.js 15 + React 19 + BlockNote (TS strict)
  app/                  App Router routes (per-workspace pages,
                        playground, settings, onboarding, auth)
  components/           app-shell, editor, entity, graph, ontology,
                        playground, ui primitives
  lib/api               typed API client + endpoint definitions

collab/                 Hocuspocus + Yjs-to-block-tree projection (Node)

docs/                   architecture (RFC alignment), comparison docs

skills/                 Agent skills library (drop-in for Claude Code)

seeds/                  Built-in ontology YAML (13 types, 15 relations)

ops/                    Postgres init SQL + Caddyfile
```

---

## Architecture summary

The full RFC is in
[`docs/architecture/rfc-001-alignment.md`](docs/architecture/rfc-001-alignment.md).
The shape:

- **Postgres 17 with pgvector / pg_trgm / tsvector / ltree / tstzrange.**
  One database, no separate triple store. JSON-LD at the API boundary
  is the semantic-web interop story; we sit between RDFS-Plus and OWL
  2 RL.
- **Bi-temporal edges + W3C PROV-O activities.** Every state-changing
  call opens a `prov_activity` row and stamps the resulting edge /
  episode. `prov_activity_derivation` links agent B's activity to the
  upstream activity of agent A.
- **Workspace RLS + sensitivity labels.** Postgres-enforced workspace
  isolation; label-policy filter runs over query results. Admin /
  owner / service principals bypass label policies.
- **Hybrid retrieval.** RRF over vector + tsvector + trigram +
  optional 1-hop graph expansion → label-policy filter → optional
  cross-encoder rerank → MMR diversify.
- **MCP server.** 22 tools registered at `/api/mcp/rpc`; the playground
  page exercises them end-to-end with a streaming Claude agent.

---

## Running tests

```bash
make test                # fast suite, no LLM calls
make test-scenario       # opt-in enterprise persona tests
make test-live           # opt-in live Anthropic call (~$0.05/run)
```

Pytest markers: `scenario`, `live_llm`. CI runs `-m "not live_llm"`.

---

## Connecting agents

Open `/[workspace]/settings/agents` in the web UI, mint a token, paste
the shown snippet into your client:

- **Claude Code** — `claude mcp add-json memory '{"type":"http","url":"…","headers":{"Authorization":"Bearer mem_…"}}' --scope user`. Tools appear under `/mcp`.
- **Cursor** — drop the JSON block into `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project).
- **Claude Desktop** — edit `claude_desktop_config.json`.

Tokens are workspace-scoped, revocable, argon2-hashed at rest, and
rate-limited per `MCP_RATE_LIMIT_RPM` (default 60). Discovery is at
`/.well-known/oauth-protected-resource` (RFC 9728); the server
advertises `protocolVersion: 2025-06-18`.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md).
The TL;DR: one PR per change, failing test before a fix, no
connector reintroductions.

## License

TBD. Contact the maintainer before redistributing or relying on this
in production.
