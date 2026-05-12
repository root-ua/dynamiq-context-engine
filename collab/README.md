# Memory Collab (Hocuspocus)

Tiny Node service providing Yjs realtime collab for BlockNote documents. Persists Yjs state in the shared `document.yjs_state` bytea column in Postgres.

Document naming: `doc:<document_id>` where `document_id` is the UUID primary key of the `document` row.

## Dev

```bash
cd collab
pnpm install
pnpm dev
# listens on :1234
```

Or via docker-compose: `docker compose up hocuspocus`.

## Week 1 scope

- Authenticate connections via shared JWT secret.
- Fetch/store Yjs state from Postgres.

## Week 2 scope

- Project Yjs doc → `block` table on `onStoreDocument` (block tree, `search_text`, `block_entity_ref` rebuild).
- Workspace authorization: verify principal's workspace owns the document.
