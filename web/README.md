# Memory Web (Next.js)

Next.js 15 + shadcn + BlockNote + Sigma.js. Human-facing editing UX for the memory platform.

## Dev

```bash
cd web
pnpm install
pnpm dev
# http://localhost:3000
```

Regenerate the typed API client from FastAPI's OpenAPI:

```bash
pnpm api:generate
```

## Layout

```
app/                 App Router pages + route handlers
  (auth)/            login, signup (BetterAuth)
  (app)/[workspace]/ workspaces scope (Week 2+)
  api/auth/          BetterAuth handler
components/          editor, graph, entity, ontology, agent, ui (shadcn)
lib/                 api client, auth config, utils
```
