# How Dynamiq compares to other agent-memory systems

This folder is a factual side-by-side. Each vendor gets a long-form
doc; this README is the summary table.

## At-a-glance matrix

| Capability | Dynamiq | Zep / Graphiti | Mem0 | Memori (LangChain) | Cognee |
|---|---|---|---|---|---|
| Typed property graph | ✅ (Postgres) | ✅ (Neo4j) | partial (entities + relations as memory items) | – | ✅ |
| Bi-temporal `valid_time` + `sys_time` ranges | ✅ (`tstzrange`) | ✅ | partial (timestamp on memory) | – | – |
| W3C PROV-O activity lineage on every fact | ✅ | – | – | – | partial |
| Per-fact sensitivity labels + policy filter | ✅ | – | – | – | – |
| Workspace RLS (multi-tenant from row 0) | ✅ (forced RLS) | – | partial | – | partial |
| Cross-agent `wasDerivedFrom` chain | ✅ | – | – | – | – |
| Hybrid retrieval (vector + FTS + trigram + graph) | ✅ | partial | partial | – | ✅ |
| Reranker (cross-encoder) | optional | – | – | – | – |
| Human-facing block editor (Notion/Obsidian-style) | ✅ | – | – | – | – |
| MCP server | ✅ (22 tools) | – (REST) | – (SDK) | – (LangChain wrapper) | partial |
| JSON-LD at the API boundary | ✅ | – | – | – | ✅ |
| Native SPARQL endpoint | ❌ | – | – | – | ✅ |
| Built-in chunking / RAG pipeline | ❌ (agent's job) | – | partial | – | ✅ |
| OWL reasoning | ❌ | – | – | – | partial |
| License | TBD | Apache 2.0 (Graphiti) / commercial (Zep Cloud) | Apache 2.0 / commercial | MIT (LangChain Memory) | Apache 2.0 |

## Where Dynamiq wins clearly

1. **PROV-O on every fact.** Every state change opens a
   `prov_activity` row. Cross-agent derivation chains are queryable
   in one MCP call. No other vendor on this list ships PROV-O.
2. **Per-fact ACL + sensitivity labels with admin bypass.** A
   label-policy layer that filters retrieval, with workspace RLS
   underneath. The closest competitor (Cognee) does row-level scoping
   but not policy.
3. **Bi-temporal `tstzrange`.** SQL:2011-style application-time on
   the edge model with GiST indexing. Zep does the same with
   Graphiti's bi-temporal edges; Mem0 / Memori only have a created-at
   timestamp.

## Where Dynamiq loses (today)

1. **No native SPARQL / OWL reasoning.** JSON-LD at the API boundary
   is the interop story; if you need SPARQL or OWL DL inference,
   Cognee is the better fit.
2. **No embedded RAG pipeline.** Chunking, parsing, deduplication of
   raw documents is the calling agent's responsibility. Cognee and
   parts of Mem0 ship their own.
3. **Smaller community.** Zep / Mem0 / LangChain Memory have
   hundreds of integrations. We've got an MCP server and a Next.js
   web app.

## When to pick Dynamiq

- You're building an enterprise product where the audit trail
  matters — finance, healthcare, legal.
- You want humans and agents editing the same knowledge graph.
- You want fine-grained sensitivity labels (`pii`, `confidential`)
  baked into retrieval, not a separate compliance layer.
- You're already on Postgres and don't want to operate a triple
  store / Neo4j cluster.

## When to pick someone else

- **SPARQL / OWL reasoning required** → Cognee.
- **Plug-and-play short-term LLM memory for a chat app** → Mem0 or
  LangChain Memory.
- **Mature managed cloud + community plugins** → Zep Cloud.
- **You want chunking + retrieval out of the box, not "bring your
  own ingest agent"** → Cognee or Zep.

## Source links

- [Zep / Graphiti](https://github.com/getzep/graphiti)
- [Mem0](https://github.com/mem0ai/mem0)
- [LangChain Memory](https://python.langchain.com/docs/modules/memory/)
- [Cognee](https://github.com/topoteretes/cognee)
