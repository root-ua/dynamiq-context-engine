# Running Dynamiq Context Engine locally

This is the end-to-end "I just cloned the repo, get me to a working
playground" walkthrough. Tested on macOS + Linux; on Windows use WSL2.

## Prerequisites

- **Docker Desktop** with Compose v2 (`docker compose version` should
  print v2.x.x).
- **Node 22 (LTS)** if you want to develop the web app outside the
  docker stack. The repo pins `22` via `.nvmrc`; run `nvm use` from
  the repo root to switch.
- **Python 3.12 + uv** if you want to run tests locally.
  `brew install uv` (macOS) or `pipx install uv`.
- **An Anthropic API key** if you want the live playground or the
  `live_llm` test. Sign up at https://console.anthropic.com if you
  don't have one.

## Quick start

```bash
# 1. Clone + env template.
git clone <repo> && cd memory-experiments
cp .env.example .env
```

Open `.env` and fill in the three required secrets:

```bash
JWT_SECRET=<32-byte hex; openssl rand -hex 32>
BETTER_AUTH_SECRET=<32-byte hex; openssl rand -hex 32>
HYDRATE_SECRET=<32-byte hex; openssl rand -hex 32>
```

Optional but recommended:

```bash
ANTHROPIC_API_KEY=sk-ant-…   # enables extraction + playground
OPENAI_API_KEY=sk-…          # enables embeddings (text-embedding-3-small)
```

Without `ANTHROPIC_API_KEY` the playground page shows a graceful
"key not configured" error; extraction silently skips. Without
`OPENAI_API_KEY` semantic search falls back to text/trigram only.

```bash
# 2. Bring up the stack.
make up
```

First boot pulls Postgres 17 (pgvector), Redis 7, the pinned MinIO
release, and builds the backend / worker / hocuspocus / web images.
Subsequent boots are ~10s.

Backend ports (mapped from container internals to avoid clashing
with anything you have running on the host):

| Service        | Container | Host  |
|----------------|-----------|-------|
| Web            | 3000      | 53000 |
| Backend API    | 8000      | 58000 |
| Hocuspocus     | 1234      | 51234 |
| Postgres       | 5432      | 55432 |
| Redis          | 6379      | 56379 |
| MinIO API      | 9000      | 59000 |
| MinIO console  | 9001      | 59001 |
| Caddy reverse proxy | 80   | 58080 |

```bash
# 3. Open the web app.
open http://localhost:53000
```

## First-time setup in the UI

1. **Sign up** with any email + password. BetterAuth is the auth
   provider; the data lands in the same Postgres.
2. **Create a workspace.** Pick a slug like `acme`; choose
   `flexible` ontology mode for the demo.
3. **Mint an MCP token.** Navigate to **Connect agents** in the
   sidebar (or `/[workspace]/settings/agents`). Click **Create
   token**, name it ("My Claude Code"), copy the plaintext that
   appears in the dialog.
4. **Hook up an external agent.** The same page renders a
   ready-to-copy snippet per client (Claude Code, Cursor, Claude
   Desktop, Claude Web, OpenAI Agents SDK, curl). Paste into your
   client; restart it; the 22 tools show up.

## Try the playground

`/[workspace]/playground` is a chat window where a real Claude
agent talks to the MCP server bound to your workspace. Things to
try:

- Type **"What's in this workspace?"** — Claude calls
  `search_memory` and reads back what it finds.
- **Drop a PDF** anywhere in the chat pane. The frontend hands the
  PDF straight to Claude as an Anthropic `document` content block
  (the platform doesn't parse PDFs — that's Claude's job). Claude
  reads it natively, decides what facts matter, and calls
  `add_episode`. Tool calls stream into the right pane.
- After ingest: **"What does this document say about X?"** — Claude
  uses `search_memory` and `get_fact` to answer with provenance.

## Run tests

```bash
# Fast suite, no LLM calls.
make test

# Scenario tests (real Postgres + Redis; slower).
make test-scenario

# Live LLM (~$0.05/run via claude-haiku-4-5). Requires ANTHROPIC_API_KEY.
make test-live
```

Lint + typecheck:

```bash
make lint        # ruff (backend) + next lint (web)
make typecheck   # mypy (backend) + tsc (web)
```

## Smoke from an external client

In a separate terminal, with `DYNAMIQ_TOKEN` and `ANTHROPIC_API_KEY`
exported:

```bash
cd examples
python -m venv .venv && source .venv/bin/activate
pip install anthropic httpx
DYNAMIQ_API_URL=http://localhost:58000 python 01-claude-builds-kg.py
```

The script will fetch `tools/list`, ask Claude (haiku) to land three
facts about Anthropic, stream the tool calls back to the terminal,
and print the final response. Total time ~30s, total cost ~$0.05.

## Troubleshooting

**`docker compose up` errors with "port already allocated".** Some
other service on the host is bound to the same port. Edit
`docker-compose.override.yml` (create it if absent — it's
gitignored) and remap. Example:

```yaml
services:
  web:
    ports:
      - "3500:3000"   # was 53000:3000
```

**`alembic upgrade head` complains about a missing extension.** The
`pgvector/pgvector:pg17` image installs pgvector + pg_trgm + ltree;
if you swapped to plain Postgres, install those manually (or use
the pinned image).

**MinIO bucket missing in tests.** The compose stack's `minio-mc`
sidecar creates the bucket on boot. If you boot just `postgres +
redis` for unit tests, the bucket isn't created and export tests
fail with `NoSuchBucket`. Either bring up the full stack or skip
the export scenario.

**Playground returns "ANTHROPIC_API_KEY is not configured".** Set
`ANTHROPIC_API_KEY` in `.env` and restart the backend
(`docker compose restart backend`). The settings are read at
process start.

**Tests hit `127.0.0.1:5432` connection refused.** The Postgres
container is bound to host port **55432**, not 5432. Either run
tests inside the container (`docker compose exec backend pytest`)
or pass `POSTGRES_URL=postgresql+asyncpg://memory:memory@localhost:55432/memory`
when invoking pytest locally.

**`uv sync` complains about Python 3.12.** Install via
`brew install python@3.12` (macOS) or `apt install python3.12-venv`
(Ubuntu). `pyproject.toml` pins 3.12 minimum.

## What to read next

- [`README.md`](../README.md) — product pitch + architecture summary.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — PR workflow + commit
  style.
- [`docs/architecture/rfc-001-alignment.md`](architecture/rfc-001-alignment.md)
  — RFC mapping for every load-bearing feature.
- [`docs/comparison/`](comparison/README.md) — side-by-side with Zep,
  Mem0, LangChain Memory, Cognee.
- [`skills/`](../skills/README.md) — drop-in agent skills.
