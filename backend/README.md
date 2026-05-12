# Memory Backend (FastAPI)

Python 3.12 + FastAPI. REST + MCP (SSE/stdio). Bi-temporal graph, hybrid retrieval, ontology validator, extraction workers.

## Layout

```
app/
  main.py                FastAPI app factory
  core/                  settings, logging
  api/
    rest/                CRUD, search, ontology HTTP endpoints
    mcp/                 MCP server (SSE + stdio)
    websocket/           LISTEN/NOTIFY stream for live UI
  auth/                  JWT verify, RLS SET LOCAL
  domain/                Entity, edge, ontology, document, merge services
  retrieval/             Hybrid search, graph expansion, rerank, context
  extraction/            Episode → entities/edges pipeline
  workers/               Arq tasks
  llm/                   LiteLLM wrapper, embedding client
  db/                    Session, migrations, models
  mcp_tools/             One file per MCP tool
tests/
```

## Dev

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Or via docker-compose from repo root: `docker compose up backend`.
