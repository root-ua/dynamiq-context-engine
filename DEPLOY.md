# Deploying Dynamiq Context Engine to Render.com

A step-by-step runbook for going from a fresh clone to a live production stack. Budget ~30 minutes for the first deploy once you have the external accounts ready.

## Prerequisites

You need accounts for:

- **Render.com** — the platform. Credit card on file (Starter plan is ~$7/mo per service).
- **An S3-compatible object store** — pick one: AWS S3, Cloudflare R2, Backblaze B2, DigitalOcean Spaces. R2 has free egress and is the cheapest at low volume.
- **Anthropic** — for extraction + contradictor (`ANTHROPIC_API_KEY`).
- **OpenAI** — for embeddings (`OPENAI_API_KEY`). You can swap to a different embedding model later, but the default schema column is sized at 1536 dims.
- **Resend** — transactional email for signup verification + password reset (`RESEND_API_KEY`). Free tier is 100/day.
- **Sentry** (optional) — error tracking. Skip if you want to defer.

## 1 — Fork / push the repo

Render needs GitHub access. Fork this repo or push it to a new GitHub repo under your org, then in Render → Account → GitHub, grant access to it.

## 2 — Create the blueprint

In Render dashboard:

1. New → **Blueprint** → pick the repo.
2. Render reads `render.yaml` and shows a preview of services to create. Confirm.
3. Before clicking Apply, Render will flag every `sync: false` env var as "requires manual entry". **Do not click Apply yet.**

## 3 — Fill in env var groups (CRITICAL — do before first build)

Render groups env vars; set them here so every service inherits consistently.

### `dynamiq-secrets`

Generate strong random values on your laptop:

```bash
openssl rand -hex 32   # JWT_SECRET
openssl rand -hex 32   # BETTER_AUTH_SECRET
```

Paste into the dashboard:

| Key | Value |
|---|---|
| `JWT_SECRET` | first hex string |
| `BETTER_AUTH_SECRET` | second hex string |

### `dynamiq-urls`

Before you have deployed anything, you won't have the final service URLs. So click through to each service in the blueprint preview, note its URL pattern (`https://<service>-<hash>.onrender.com`), and fill in. You can rename services before the first build to get predictable URLs.

| Key | Value |
|---|---|
| `PUBLIC_BASE_URL` | `https://dynamiq-backend-XXXX.onrender.com` |
| `CORS_ORIGINS` | `https://dynamiq-web-XXXX.onrender.com` |
| `BETTER_AUTH_URL` | `https://dynamiq-web-XXXX.onrender.com` |
| `NEXT_PUBLIC_API_URL` | same as `PUBLIC_BASE_URL` |
| `NEXT_PUBLIC_COLLAB_URL` | `wss://dynamiq-hocuspocus-XXXX.onrender.com` (note: **wss://** not **https://**) |
| `NEXT_PUBLIC_BETTER_AUTH_URL` | same as `BETTER_AUTH_URL` |
| `NEXT_PUBLIC_SITE_URL` | same as `BETTER_AUTH_URL` |

**Important**: `NEXT_PUBLIC_*` are baked into the web bundle at **build** time, not injected at runtime. If they aren't set before the first build, the browser will call `undefined/api/...` and nothing will work. Re-deploy the web service after changing any of these.

### `dynamiq-integrations`

| Key | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from console.anthropic.com |
| `OPENAI_API_KEY` | from platform.openai.com |
| `RESEND_API_KEY` | from resend.com |
| `S3_ENDPOINT` | e.g. `https://<account>.r2.cloudflarestorage.com` |
| `S3_ACCESS_KEY` | bucket access key |
| `S3_SECRET_KEY` | bucket secret |
| `S3_BUCKET` | `dynamiq-attachments` (create it first) |
| `S3_REGION` | `auto` (R2) / `us-east-1` (AWS) / ... |
| `SENTRY_DSN` | optional; leave blank to disable |

## 4 — Apply the blueprint

Click Apply in Render. It will:

1. Create `dynamiq-postgres` (takes ~1 min to provision).
2. Create `dynamiq-redis`.
3. Build + deploy the four services in parallel.

The backend service has `preDeployCommand: alembic upgrade head`, so migrations run once before traffic is swapped — no race on scale-up.

## 5 — Verify

Once every service shows "Live":

```bash
# Backend health
curl https://dynamiq-backend-XXXX.onrender.com/api/health
# → {"status":"ok"}

# MCP discovery
curl https://dynamiq-backend-XXXX.onrender.com/.well-known/oauth-protected-resource
# → {"resource":"…/api/mcp","authorization_servers":[…]}

# Web
curl -I https://dynamiq-web-XXXX.onrender.com/
# → HTTP/2 200, security headers present
```

Open the web URL in a browser:

1. Sign up with a real email.
2. Check inbox for the verification email (from Resend — check "From" sender matches your configured domain).
3. Click verify → land on onboarding → create workspace → sample data should load.

## 6 — Point a custom domain

In Render → the web service → Settings → Custom Domains. Add `app.yourdomain.com`, follow the CNAME instructions.

Then update these env vars:

- `NEXT_PUBLIC_SITE_URL` → `https://app.yourdomain.com`
- `BETTER_AUTH_URL` → `https://app.yourdomain.com`
- `NEXT_PUBLIC_BETTER_AUTH_URL` → `https://app.yourdomain.com`
- `CORS_ORIGINS` → `https://app.yourdomain.com`

Redeploy the web service (NEXT_PUBLIC_* changed). Redeploy backend (CORS changed).

## Backups + DR

- **Postgres**: Render Starter keeps 7 days of automatic backups. To restore, use the Render dashboard → database → Backups.
- **S3 bucket**: your object store provider's own backup controls. Most CDN bucket services include object versioning — enable it.
- **Secrets**: store `JWT_SECRET` and `BETTER_AUTH_SECRET` in a password manager. Losing `JWT_SECRET` invalidates every live session.

## Migrations after first deploy

Every subsequent push to `main` (with autoDeploy: true) will:

1. Build new images
2. Run `preDeployCommand: alembic upgrade head` (zero-downtime since backend is still serving old traffic)
3. Swap traffic to new instances

If a migration needs manual attention, set `autoDeploy: false` on the backend service, deploy, and run migrations as a one-shot job from the Render shell before re-enabling.

## Rolling back

1. Render → service → Deploys → pick the previous good deploy → Rollback.
2. If the rollback spans a migration, you need to run `alembic downgrade -1` **first** from Render shell, then rollback. The `downgrade()` function is defined in every migration in this repo.

## RFC-001 alignment env vars

Added in the Phase A–H passes. All have sensible defaults; override
only if you need to tighten or relax the defaults.

| Var | Default | What it controls |
|---|---|---|
| `DEFAULT_EXTRACTION_THRESHOLD` | `0.7` | Per-class `min_confidence` for new workspaces. Facts below this confidence land in `/review` instead of going live. |
| `DEFAULT_AUTO_REJECT_BELOW` | `0.3` | Anything strictly below this is recorded as `pending_fact(status='rejected')` for audit, never enqueued. |
| `ENTITY_RESOLVER_LLM_MODEL` | `claude-haiku-4-5` | Cheap judge for the tier-3 entity-resolution cascade. |
| `RERANKER_ENABLED` | `false` | Master switch on the cross-encoder rerank stage in hybrid retrieval. Adds latency and an extra dep (sentence-transformers) — turn on when you have the budget. |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model id used when `RERANKER_ENABLED=true`. |
| `RERANKER_TOP_N` | `30` | How many top fused candidates pass through the reranker before MMR. |
| `AUDIT_LOG_RETENTION_DAYS` | `365` | Daily cron purges `audit_log` rows older than this. Set to `0` to disable. |
| `WORKER_DRAIN_SECONDS` | `30` | Cap on graceful drain after SIGTERM; the Arq worker exits hard after this. |

### Per-workspace settings (JSONB on `workspace.settings`)

- `edge_retention_days` — closed-edge retention window (Phase QQ4).
  Daily cron `purge_closed_edges` (03:43 UTC) hard-deletes edges
  whose `sys_time` was closed more than N days ago. `0` (default)
  disables purge for that workspace. Provenance (`prov_activity`,
  `audit_log`) survives. Set via `PATCH /api/workspaces/:id`
  or the workspace settings page.

| `PLAYGROUND_MODEL` | `claude-sonnet-4-6` | Model used by the chat-style playground page. |
| `MCP_RATE_LIMIT_RPM` | `60` | In-memory per-token requests-per-minute cap on `/api/mcp/*`. Set to `0` to disable. |

See `docs/architecture/rfc-001-alignment.md` for the full per-section
status table.

## Cost floor (Starter plans, as of 2026)

- Postgres Starter: ~$7/mo
- Redis Starter: ~$10/mo
- 4× web services Starter: ~$7/mo each = $28/mo

Total ~$45/mo. Bump any service to Standard ($25/mo) when you see sustained CPU pressure or need more RAM.
