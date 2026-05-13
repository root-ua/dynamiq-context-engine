# Dynamiq vs Cognee

## Pitch

[Cognee](https://github.com/topoteretes/cognee) is the closest project
to Dynamiq on the standards axis. It combines a graph store (Neo4j /
NetworkX / FalkorDB), a vector store, and an RDF/SHACL layer with
Pydantic schema validation. The pitch is "memory for AI agents with
the semantic-web stack baked in".

## Data model

Cognee separates **DataPoints** (typed Pydantic models) from
**RDF / SHACL** definitions. You declare a Pydantic model, Cognee
extracts instances from text, and you can query with SPARQL or graph
traversal.

Dynamiq uses a typed property graph in Postgres. We sit between
RDFS-Plus and OWL 2 RL: typed entities, relations with domain /
range / inverse / symmetric / transitive flags, but no full OWL DL
reasoner, no embedded SPARQL.

| | Dynamiq | Cognee |
|---|---|---|
| Typed graph | ✅ (Postgres) | ✅ (multiple backends) |
| Bi-temporal | ✅ (`tstzrange`) | – |
| W3C PROV-O | ✅ | partial |
| JSON-LD at API | ✅ | ✅ |
| SPARQL endpoint | ❌ | ✅ |
| OWL DL reasoning | – | partial |
| Chunking + RAG pipeline | – (agent's job) | ✅ |
| MCP server | ✅ | partial |

## Standards

- **RDF/SPARQL** — Cognee exposes a SPARQL endpoint. Dynamiq does
  not; JSON-LD at the API is the interop story.
- **SHACL** — Cognee does shape validation on ingested data. Dynamiq
  uses Pydantic + JSON Schema for the same job.
- **PROV-O** — Dynamiq emits it on every fact with activity lineage
  and cross-agent derivation chains. Cognee has partial provenance
  metadata; not as deep.

## Permissioning

- Dynamiq: workspace RLS + sensitivity-label policy.
- Cognee: row-level scoping where the backing store supports it.

## Provenance

- Dynamiq: PROV-O activity + agent + derivation, queryable in one
  MCP call.
- Cognee: tracks source documents and chunks; not a formal activity
  graph.

## Agent surface

- Dynamiq: MCP-native (22 tools).
- Cognee: Python SDK + REST; MCP support is partial / experimental.

## License

- Dynamiq: TBD.
- Cognee: Apache 2.0.

## When to pick which

**Pick Cognee if** you need SPARQL, OWL DL, or you want a built-in
RAG pipeline (chunking, extraction, retrieval) rather than the
"bring your own ingestion agent" model.

**Pick Dynamiq if** you need MCP-first integration, bi-temporal
queries, audit-grade PROV-O, and the rest of the operational story to
fit in one Postgres database. The two projects have similar values
but make different bets — Cognee bets on semantic-web depth, Dynamiq
bets on operational simplicity + agent-first surface.
