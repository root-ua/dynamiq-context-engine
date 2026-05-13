# Dynamiq vs Mem0

## Pitch

[Mem0](https://github.com/mem0ai/mem0) is "LLM-as-memory-controller":
a small operation set (`add` / `update` / `delete` / `noop`) the LLM
issues against a memory store, with a hybrid graph + vector index
under the hood. The hosted service handles short-term + long-term
memory for chat apps.

## Data model

Mem0 stores **memory items** — typed records with content, metadata,
embedding, and (optionally) extracted entities and relations. Memory
items are organised by `user_id` / `agent_id` / `run_id` scopes.

Dynamiq stores **entities** and **edges** in a typed bi-temporal
property graph. Episodes are first-class records of raw input;
extraction turns them into entities + edges through an LLM pipeline.

| | Dynamiq | Mem0 |
|---|---|---|
| Bi-temporal edges | ✅ (`tstzrange`) | partial (timestamp on item) |
| Typed ontology with subclass hierarchy | ✅ (`ltree`) | freeform |
| W3C PROV-O activity lineage | ✅ | – |
| Per-item ACL | workspace RLS + labels | scope-based |
| LLM-driven memory ops (add/update/delete) | implicit (extraction + invalidate) | explicit |

## Standards

- **JSON-LD** — Dynamiq emits at the API boundary; Mem0 does not.
- **PROV-O** — Dynamiq honors W3C PROV-O. Mem0 has no formal
  provenance layer.
- **MCP** — Dynamiq's primary surface. Mem0 is SDK-first with
  optional REST.

## Permissioning

- Dynamiq: workspace RLS + sensitivity-label policy. Multi-tenant
  from row 0; every row carries `workspace_id`.
- Mem0: scopes (`user_id`, `agent_id`, `run_id`). Multi-tenancy is
  the application's responsibility outside those scopes.

## Provenance

- Dynamiq: every fact links to the LLM activity that produced it +
  the source episode it was derived from. `derived_from_activity_ids`
  on `add_fact` records cross-agent lineage.
- Mem0: `metadata` is freeform; you can stuff a "source" key in
  there. No formal provenance graph.

## Agent surface

- Dynamiq: MCP server + REST. 22 tools.
- Mem0: Python / TS SDKs; REST API on the hosted product.

## License

- Dynamiq: TBD.
- Mem0: Apache 2.0 (open source); commercial cloud.

## When to pick which

**Pick Mem0 if** you're building a chat app that needs "memory in
under 20 lines of code" and the LLM-driven op-set fits your mental
model. Mem0's scope is conversational memory.

**Pick Dynamiq if** you need a typed knowledge graph with audit-grade
provenance, multi-tenant RLS, and a human editor on the same store.
Dynamiq's scope is enterprise knowledge.
