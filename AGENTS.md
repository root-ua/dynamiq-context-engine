# AGENTS.md

Onboarding for humans and coding agents (Claude Code, Cursor, Aider, codex-style assistants) contributing to this repo.

**Product reader? Start with [README.md](README.md).**

This file is the short version of everything you need to change code safely. It covers (1) the mental model, (2) the dev workflow, (3) code conventions, (4) standing non-negotiables, (5) landmines we've paid for in past sessions, and (6) task recipes for common operations.

---

## 1. Mental model in 90 seconds

Six load-bearing ideas. If any of them starts drifting in your head, pause and re-read this section.

1. **Episodes are ground truth; everything else is derived.** Never mutate an episode. Entities and edges are re-derivable from episodes via the extraction pipeline. If you find yourself wanting to "fix" data in place, add a new episode or invalidate an edge instead.

2. **Typed property graph in Postgres.** Adjacency tables (`entity`, `edge`) + JSONB + `ltree` for type hierarchy. Not RDF. Not [Apache AGE](https://age.apache.org). The OWL-style concepts we honor (subtyping, inverse/symmetric/transitive, `owl:sameAs` merge) are modeled with flags and triggers, not a triple store.

3. **Bi-temporal edges.** Every edge has `valid_time` (when the relation is true in the world) and `sys_time` (when the system believes it). Both are `tstzrange`. Invalidate, never delete. Use `clock_timestamp()` for the `sys_time` axis inside a transaction — `now()` is transaction-stable and collapses same-txn ranges to empty. The DB has `CHECK (NOT isempty(sys_time))` / `CHECK (NOT isempty(valid_time))`; if you hit it, you're probably misusing `now()`.

4. **Shared ontology.** Humans edit types and relations in the UI; agents call `create_entity_type` / `create_relation_type` / `propose_ontology` via MCP. [JSON Schema](https://json-schema.org) validates entity props in three places (Postgres via `pg_jsonschema`, Python via `jsonschema`, React via `@rjsf/core`). The same schema powers the auto-generated UI form.

5. **Multi-tenant RLS is forced.** Every workspace-scoped table has a `workspace_id` column with an RLS policy. Every query runs inside a transaction that `SET LOCAL app.current_workspace_id = ...` reads from the JWT. No exceptions. PGbouncer must be in transaction mode, not session mode, or `SET LOCAL` won't survive.

6. **LLM-as-memory-controller with a small op set.** Agent writes go through `add_fact` / `update_entity` / `invalidate_fact` / noop. High-stakes relations (`relation_type.high_stakes = true`) run through the contradictor before insert.

---

## 2. Where to start reading

Trace the happy path in this order:

| Step | File | What you learn |
|---|---|---|
| 1 | `backend/app/domain/edge.py` | The bi-temporal heart. `add_fact`, `invalidate`, `as_of`, cardinality-one auto-close. |
| 2 | `backend/app/domain/ontology.py` | Types/relations, hierarchy via ltree, JSON-Schema validator. |
| 3 | `backend/app/api/mcp/tools.py` | The 12 agent tools; one file per input/handler pair. |
| 4 | `backend/app/api/rest/__init__.py` | How REST routes compose. |
| 5 | `backend/app/auth/deps.py` | JWT verify → RLS `SET LOCAL` — the tenancy boundary. |
| 6 | `backend/app/db/migrations/versions/` | Three files, the entire schema. Read 0001 first. |
| 7 | `web/components/editor/Editor.tsx` | BlockNote + Yjs + Hocuspocus wiring. |
| 8 | `web/components/editor/serialize.ts` | Yjs → block tree projection (SSoT for SQL queries). |
| 9 | `web/app/(app)/[workspace]/layout.tsx` | Auth gate + sidebar + topbar shell. |
| 10 | `seeds/ontology.yaml` | What ships with every new workspace. |

After these, you can follow individual features by tracing from a page (`web/app/(app)/[workspace]/<feature>/page.tsx`) to the typed API client (`web/lib/api/endpoints.ts`) to the REST handler (`backend/app/api/rest/<feature>.py`) to the domain service (`backend/app/domain/<feature>.py`).

---

## 3. Dev workflow

```bash
# Bring the stack up (first boot auto-runs migrations)
docker compose up --build -d

# Tail logs
docker compose logs -f backend web backend-worker

# Web gate — run before every commit (format + lint + typecheck + vitest)
docker compose exec -T web pnpm check

# Backend gate
docker compose exec -T backend pytest
docker compose exec -T backend ruff check .

# Playwright E2E (stack must be up)
docker compose exec -T web pnpm exec playwright test

# After a pyproject.toml / backend Dockerfile change
docker compose build backend
docker compose up -d backend backend-worker

# After a new web dependency
docker compose exec -T web pnpm install

# Regenerate the typed API client from FastAPI's OpenAPI
docker compose exec -T web pnpm api:generate
```

**Pre-commit.** A husky hook at `.husky/pre-commit` runs `lint-staged` + `typecheck` + `test` on any `web/**` change. On first setup inside a git-initialized repo, `pnpm install` runs `prepare` which configures `git config core.hooksPath .husky`.

**CI.** `.github/workflows/web-ci.yml` mirrors `pnpm check` + `pnpm build` on push/PR. If you add a backend CI job later, mirror `ruff check .` + `pytest`.

---

## 4. Code conventions

- **Comments: only for WHY.** Never restate what the code does — well-named identifiers do that. Add a comment when a reader would reasonably ask "why isn't this the obvious thing?" File-level docstrings are welcome when they explain a non-obvious contract (e.g., "this service keeps a module-level async pool; callers must use `session_scope` or RLS breaks").
- **Raw SQL over ORM** in the domain layer. We're Postgres-only; the ORM is a translation layer we don't want. Alembic migrations are the only place ORM models would even be considered, and even there we prefer `op.execute("CREATE TABLE ...")` because we lean heavily on Postgres-specific features (tstzrange, ltree, RLS, triggers) that SQLAlchemy's ORM abstracts poorly.
- **TypeScript strict.** `strict`, `noUncheckedIndexedAccess`, `noUnusedLocals`, `noUnusedParameters`, `noImplicitOverride`. Zero `any` (`@typescript-eslint/no-explicit-any` is an error). Prefer `unknown` + a narrowing type guard.
- **Python strict.** `ruff` with the config in `backend/pyproject.toml`; `mypy strict` where it runs clean. Use `ClassVar` for mutable class attributes (Arq `WorkerSettings` is the only exception — the ClassVar annotation conflicts with Arq's introspection).
- **ESLint.** `@typescript-eslint/recommended-type-checked` + `stylistic-type-checked` + `prettier`. `no-floating-promises` is an error — prefix event-handler fire-and-forgets with `void` (`void router.push("/home")`). `consistent-type-imports` is enforced — use `import type { Foo } from "..."` or `import { type Foo } from "..."`.
- **Prettier** runs via pre-commit + CI `format:check`. Config: semi, double-quote, trailing-comma-all, 80 col, Tailwind class sort. Don't fight it.
- **Test patterns:**
  - Backend: `pytest` + `pytest-asyncio` + `testcontainers` (live Postgres). Fixtures in `backend/tests/conftest.py` seed a fresh workspace per test.
  - Web: `vitest` + `@testing-library/react`. See `web/components/entity/EntityForm.test.tsx` for the regression pattern (assert DOM shape, e.g., "does NOT render `<form>` inside another `<form>`").
  - Mock `next/navigation` in `web/vitest.setup.ts` once; don't re-mock per test unless you need a custom router.

---

## 5. Standing non-negotiables (drift guard)

If you find yourself considering any of these, pause and re-read:

- **Don't adopt Apache AGE.** Adjacency tables + `ltree` + JSONB + recursive CTEs win on operational simplicity and managed-Postgres compatibility.
- **Don't use Yjs as long-term storage.** Yjs is the collab wire format. The `block` table is the SSoT for SQL queries; the `block_entity_ref` index is rebuilt on every save.
- **Don't run OWL DL reasoning in the request path.** Ontology checks are JSON Schema + SHACL-lite only. A reasoner belongs in a background job or a sidecar, never in the hot read path.
- **Don't introduce SPARQL as the primary query surface.** REST + MCP are the two blessed surfaces. An Oxigraph read-side projection is an acceptable v1.1+ addition.
- **Invalidate, never delete.** Edge deletion is `sys_time` closure. Block deletion is a tombstone. Entity deletion is a soft-delete flag. Episode deletion is forbidden.
- **JSON-LD at the API boundary.** `GET /api/entities/{id}?format=jsonld` is the outward contract. Internal handlers use asdict Pydantic; the JSON-LD wrap happens at the response serializer.
- **`SET LOCAL app.current_workspace_id` inside every transaction.** Not session-scoped, not global. `session_scope(workspace_id=..., user_id=...)` is the only blessed entry point.
- **Pin compat-sensitive dependencies.** Currently:
  - `prosemirror-view@1.33.8` — pinned via `pnpm.overrides` because `__serializeForClipboard` was removed in 1.34+ and BlockNote 0.22.0 still depends on it.
  - `@vitejs/plugin-react@^4` — v6 requires Vite 8; vitest bundles Vite 5.
  - `@rjsf/utils@^5.24` — has to match `@rjsf/core@5.x`; pnpm auto-resolves to 6 otherwise.

---

## 6. Landmines we've paid for

Fix in place if you hit these; don't work around.

### Alembic migrations

- **`:true` inside `op.execute(...)` is parsed as a SQLAlchemy named bind.** When writing a JSONB DEFAULT like `'{"additionalProperties":true}'::jsonb`, drop the property or replace with a JSONB builder (`jsonb_build_object(...)`). Similarly for `:false` and `:word` patterns.
- **`symmetric` is a PostgreSQL reserved keyword.** Quote it as `"symmetric"` in every raw-SQL reference (column def, SELECT list, UPDATE SET, WHERE, EXCLUDED qualified access).
- **Alembic env.py uses sync URL.** `psycopg2-binary` is required even though the runtime uses asyncpg. It's in `backend/pyproject.toml` — don't remove it.
- **Put idempotent DDL in migrations** (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). Migration 0003 relies on this so first-boot after a manual BetterAuth CLI run still applies clean.

### SQL + asyncpg

- **`tstzrange(lower(sys_time), now(), '[)')` collapses to an empty range** inside a single transaction because `now()` = `transaction_timestamp()` is constant within a txn. Use `clock_timestamp()` for the sys axis.
- **`COALESCE(:x, 'infinity')` needs `::timestamptz`** when `:x` is a timestamptz parameter. asyncpg otherwise binds the param as `text` and the `tstzrange(timestamptz, text, text)` call fails with `UndefinedFunctionError`.
- **`jsonb_build_object('k', $1)` with untyped params fails asyncpg type inference.** Wrap each value in `CAST(:x AS text)` / `CAST(:x AS uuid)` as appropriate. When mixing casts, also cast in the `WHERE` clause so asyncpg doesn't flip-flop on the param type.
- **`WHERE e.id = $1` where `$1` is also used in a text-cast elsewhere** — asyncpg picks one type and sticks to it. Explicit `CAST(:id AS uuid)` in the WHERE clause disambiguates.
- **Insert before update when creating an edge that closes its predecessor.** The `edge.invalidated_by` FK points back at `edge(id)`; if the UPDATE runs before the INSERT of the new edge, you get a `ForeignKeyViolationError`. Pattern: pre-generate the new edge's id, INSERT the new edge, then UPDATE the old with `invalidated_by = :new_id AND id <> :new_id`.
- **`as_of(valid_at)` without a `sys_at` should NOT filter `upper(sys_time) = 'infinity'`.** That restriction means "current system view" which is narrower than what callers usually want. Document clearly what variant you're querying.

### BetterAuth + auth boundary

- **BetterAuth generates nanoid user IDs by default.** Our schema uses UUIDs. Set `advanced.database.generateId: "uuid"` in `web/lib/auth.ts`. Also ensure the `user.id` column has `DEFAULT gen_random_uuid()::text` (migration 0003 does this); BetterAuth with Kysely delegates id-gen to the DB when `supportsUUIDs` is true.
- **Mirror BetterAuth user → `app_user` via `databaseHooks.user.create.after`.** `workspace_member.user_id` FKs point at `app_user(id)`. Without the hook, workspace creation fails with a FK violation.
- **JWT `sub` claim is the BetterAuth user id** (UUID). The Next.js `/api/auth/token` mint copies it through; FastAPI verifies with the same `JWT_SECRET`.

### Next.js 15 + Tailwind

- **Next 15 auto-optimizes a built-in list of icon packages via a barrel loader.** The loader can't resolve `react-icons/pi` subpath exports; pages 500 with `'PiFoo' is not exported from __barrel_optimize__...`. Opt out with `experimental.optimizePackageImports: []` in `next.config.js`.
- **`geist/font` exposes CSS variables as `--font-geist-sans` / `--font-geist-mono`** (not `--font-sans` / `--font-mono`). Reference those exact names in `globals.css` and `tailwind.config.ts` fontFamily.
- **BlockNote type-identity issue** — with the `prosemirror-view` pin, pnpm can briefly materialize two copies of `@blocknote/core` in the tree, leading to "two different types with this name exist, but they are unrelated" typecheck errors. Workaround in `web/components/editor/serialize.ts`: `projectEditor(editor: { document: unknown }): ...` — structural type instead of `BlockNoteEditor`-nominal.
- **Next.js ESLint CLI (`next lint`)** is deprecated in 15.5 but still works. Migrating to `eslint --flat-config` is a v1.1+ chore; the `.eslintrc.js` legacy config we ship is the blessed setup for now.

### Docker

- **Bind mount `./backend:/app` overwrites image file modes.** `chmod +x docker-entrypoint.sh` on the **host** — the Dockerfile-level chmod doesn't survive the volume mount at runtime.
- **`backend-worker` env needs `JWT_SECRET` / `JWT_ALGORITHM` / `JWT_ISSUER`.** pydantic `Settings` requires them; the worker crashloops without them. They're in `docker-compose.yml` now — don't remove.
- **`docker compose down` preserves volumes, but web's `/app/node_modules` is an anonymous volume** that persists across restarts. If you added deps in a prior session, the volume might be stale; run `pnpm install` after restart if you see module-not-found errors.
- **`docker compose down -v` wipes Postgres data** (users, workspaces, entities, edges). Only do it for first-boot testing.

### pytest-asyncio

- **Set `asyncio_default_fixture_loop_scope = "session"` and `asyncio_default_test_loop_scope = "session"`** in `pyproject.toml`. The module-level asyncpg pool in `app.db.session` breaks when the loop closes mid-suite; session scope pins the loop.

---

## 7. Task recipes

### Add a new MCP tool

1. Edit `backend/app/api/mcp/tools.py`.
2. Add a Pydantic input schema (`class MyToolIn(BaseModel): ...`).
3. Write an async handler `async def _my_tool(session, workspace_id, user_id, payload): ...`.
4. Register it in the `TOOLS` list with `ToolSpec(name=..., description=..., input_schema=MyToolIn, handler=_my_tool)`.
5. The web agent console auto-renders the form from the JSON schema — no UI change needed.
6. Add a test in `backend/tests/test_mcp.py` that asserts the tool appears in the registry and its schema is valid.

### Add a new entity type at runtime

- UI: `/ontology → New type` in a workspace.
- REST: `POST /api/ontology/types` with `{name, slug, extends, schema, ui_hints}`.
- MCP: `create_entity_type` with the same shape.
- Slugs are normalized to snake_case; `-` becomes `_`.

### Add a new relation type

- UI: `/ontology → Relations tab → New relation`.
- REST: `POST /api/ontology/relations` with `{name, slug, domain, range, cardinality_subject, cardinality_object, symmetric, transitive, temporal, high_stakes, inverse_of}`.

### Add a new Alembic migration

```bash
docker compose exec -T backend alembic revision -m "short description"
```

Edit the generated file. The entrypoint auto-applies on next `docker compose up -d backend`. If you need to alter an existing raw-SQL block, remember: raw `:true` / `:false` tokens are SQLAlchemy binds — use PG literals in a different way or `op.execute(text(...).bindparams(...))`.

### Add a new REST endpoint

1. Put the route under `backend/app/api/rest/<feature>.py` using the `@router` pattern.
2. Include the router in `backend/app/api/rest/__init__.py`.
3. Add REST tests to `backend/tests/test_rest_end_to_end.py` using the authed `client` fixture.
4. Regenerate the web client: `pnpm api:generate`.
5. Add the call in `web/lib/api/endpoints.ts`.

### Add a new UI page

1. Create `web/app/(app)/[workspace]/<feature>/page.tsx`.
2. Use `useWorkspace()` for the active workspace; the `[workspace]/layout.tsx` guards auth + selects the workspace by slug.
3. Use the typed API client via `@tanstack/react-query` — no `fetch` calls in components.
4. Add the nav entry in `web/components/app-shell/nav-config.ts`.
5. Add a Vitest test for any non-trivial render logic (see `components/app-shell/nav-config.test.ts`).

### Fix a failing backend test

1. Run it alone: `docker compose exec -T backend pytest tests/test_foo.py::test_bar --tb=long`.
2. Scan the "Landmines" section above — odds are it's an asyncpg type inference or a `now()`-vs-`clock_timestamp()` issue.
3. Test DB is persistent across test runs; `conftest.py` creates a unique workspace slug per test so concurrent runs don't collide.

---

## 7b. RFC-001 v3 alignment contracts

Four post-MVP subsystems shipped in the alignment pass (see
`docs/architecture/rfc-001-alignment.md` for the per-section status):

### Provenance contract (PROV-O)

Every edge, episode, and entity_attribute may attribute itself to a
single `prov_activity` row (`backend/app/domain/provenance.py`). The
extraction pipeline opens an activity at the start of a run and closes
it after writing outputs. Read-side: `GET /api/provenance/edge/:id`
returns JSON-LD with the `prov:` namespace. MCP exposes
`get_provenance(fact_id)`.

**Rule:** if you add a new code path that produces edges or episodes,
open an activity (`prov.start_activity(...)`) and pass `prov_activity_id`
through to the writer. Tests can stub this with `kind='manual_edit'`.

### Proposal / review queue contract

`edge.add_fact` writes through directly. `edge.propose_fact` consults
`extraction_policy` and routes the fact to `edge` / `pending_fact` /
auto-reject based on confidence. Extraction MUST go through
`propose_fact`. High-stakes contradictions also route to pending
regardless of confidence — approval there explicitly authorizes closing
the prior fact.

REST: `/api/proposals[?status=]`, `:id/approve|reject`. MCP:
`list_proposals`, `approve_proposal`, `reject_proposal`.

### Sensitivity labels & policy contract

Labels live on `sensitivity_label` (ltree hierarchy). Edges and episodes
carry many-to-many label assignments. `label_policy` rows declare rules
in JSONB. `apply_label_policy` runs after RRF fusion and before MMR in
hybrid retrieval — dropping, warning, or blocking candidates based on
their assigned labels and the principal's role.

Supported rule kinds (extend in `app/domain/sensitivity.py`):
- `{"kind": "mutually_exclusive", "labels": [...]}`
- `{"kind": "requires_role", "labels": [...], "roles": ["admin","owner"]}`

REST: `/api/labels`, `/api/label-policies`. MCP: `list_labels`,
`assign_label`.

### Action contracts

Action types are registered through
`action_mod.register_action_type` and their handlers via
`@register_handler(slug)`. Invocation is idempotent on
`(workspace_id, action_type_id, idempotency_key)`. The built-in action
is `attach_evidence_to_fact` (appends evidence to `edge.props.evidence`;
optional Drive write-back).

REST: `/api/action-types`, `/api/actions/:slug/invoke`,
`/api/actions/invocations[?status=]`. MCP: `list_action_types`,
`execute_action`, `list_action_invocations`.

## 8. Further reading

- **[README.md](README.md)** — product overview + stack + quickstart.
- **[backend/README.md](backend/README.md)** — backend dev quickstart.
- **[web/README.md](web/README.md)** — web dev quickstart.
- **[collab/README.md](collab/README.md)** — Hocuspocus sidecar scope.
- **[seeds/ontology.yaml](seeds/ontology.yaml)** — built-in types + relations.

External deep dives worth your time before touching the bi-temporal or ontology layer:

- **[Zep Graphiti](https://github.com/getzep/graphiti)** — the closest public analog; read their README and bi-temporal edge doc.
- **[MCP specification](https://modelcontextprotocol.io/specification)** — tool schemas, transport layers, server behavior.
- Snodgrass, *Developing Time-Oriented Database Applications in SQL* (1999) — the bi-temporal bible. SQL:2011 [temporal features](https://en.wikipedia.org/wiki/SQL:2011#Temporal_support) summarize what the standard made official.
- **[OWL 2 Profiles](https://www.w3.org/TR/owl2-profiles/)** — know where RDFS-Plus ends and OWL RL begins so you can explain where this project sits.
- **[JSON-LD 1.1](https://www.w3.org/TR/json-ld11/)** + **[schema.org](https://schema.org)** — our outward vocabulary on the API boundary.
