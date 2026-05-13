# Contributing

This is a small repo with strong opinions. The shape of contributions
that get merged quickly looks like:

- One PR per change. Bug fix, feature, refactor — separate PRs.
- A failing test before a fix. Red → green is the default workflow.
- A note in the PR description about what changed, why, and how to
  verify it locally.

## Local setup

```bash
# 1. Clone, copy env template.
git clone <repo> && cd memory-experiments
cp .env.example .env
# Fill in JWT_SECRET, BETTER_AUTH_SECRET, HYDRATE_SECRET
# (any random 32-byte hex), plus ANTHROPIC_API_KEY if you want
# extraction / playground / live tests.

# 2. Bring up the stack.
make up

# 3. Open the web app.
open http://localhost:3000
```

`make up` builds the backend / worker / hocuspocus / web images, runs
the Alembic migration container to head, and starts every service.
Postgres / Redis / MinIO use named volumes; the first boot pulls
`pgvector/pgvector:pg17` and a pinned MinIO release.

## Running tests

```bash
# Fast suite, no LLM calls.
make test

# Scenario tests (a real Postgres + Redis are required; slower).
make test-scenario

# Live LLM end-to-end test. Costs ~$0.05 per run via claude-haiku-4-5.
# Requires ANTHROPIC_API_KEY in .env.
make test-live
```

Pytest markers:

- `scenario` — opt-in, exercises full enterprise personas.
- `live_llm` — opt-in, requires `ANTHROPIC_API_KEY`. CI never runs it.

## Adding a migration

```bash
cd backend
uv run alembic revision -m "<short_subject>" --rev-id $(date +%Y%m%d_%H%M)
```

Migrations live under `backend/app/db/migrations/versions/`. Follow the
existing pattern: top-level docstring explaining *why*, no schema-only
diffs without an explanation. Downgrades should restore the prior
shape unless the migration is genuinely one-way (e.g. the
``20260514_0001_drop_connectors`` removal); in that case raise a
``RuntimeError`` from ``downgrade`` so the operator notices.

## Commit message style

We look like this:

```
feat(retrieval): tighten cross-encoder rerank fallback

Why: the cross-encoder occasionally errors on empty payloads; we were
silently failing the query. Caller now sees a synthesized score and a
warning in the log.
```

Subject line under 70 chars, scope in parens, present tense. The body
explains the *why* — the diff already shows the *what*.

## Code style

- Backend: ruff for lint + format, mypy for types. Run `make lint` and
  `make typecheck` before pushing.
- Web: `pnpm lint`, `pnpm typecheck` (or `make lint` / `make typecheck`).
- No trailing inline `// noqa` / `// @ts-ignore` without an attached
  explanation comment.
- No empty docstrings.

## RFC alignment

Architectural changes go through `docs/architecture/rfc-001-alignment.md`.
When a PR shifts the contract — adds an MCP tool, removes a column,
flips an ACL behaviour — update the alignment doc in the same PR.

## Don't open a PR that

- Lands a feature flag without explaining the rollout / kill path.
- Adds a connector or "data ingestion as a platform feature". Ingestion
  is the calling agent's job by design — see Phase R in the RFC
  alignment doc for the reasoning.
- Skips hooks (`--no-verify`) or bypasses signing. If a hook breaks,
  fix the hook.
