# Dynamiq vs Zep / Graphiti

## Pitch

[Zep](https://www.getzep.com) is a managed agent-memory service; the
open-source kernel is [Graphiti](https://github.com/getzep/graphiti).
Graphiti is closest in spirit to Dynamiq: a bi-temporal property
graph that lands LLM-extracted facts with `valid_time` + `sys_time`
and a write-time contradictor on high-stakes predicates.

## Data model

Graphiti stores nodes and edges in Neo4j. Each edge has:
- `valid_at` / `invalid_at` for application time.
- `created_at` / (implicit) system time.
- An LLM-generated `fact` string + a `summary`.

Dynamiq stores the same shape in Postgres 17 (no separate graph DB).
Both axes (`valid_time`, `sys_time`) are explicit `tstzrange` columns
with GiST indexes for `@>` containment queries. The two stores
diverge sharply on what else they track per edge:

| | Dynamiq | Graphiti |
|---|---|---|
| W3C PROV-O activity link | ✅ every edge | – |
| Cross-agent `wasDerivedFrom` chain | ✅ | – |
| Source episode id | ✅ | partial (`source_node_uuid`) |
| Per-fact sensitivity label | ✅ | – |
| Confidence score | ✅ explicit | partial (LLM-judged) |
| Workspace RLS | ✅ Postgres-enforced | external |

## Standards

- **PROV-O** — Dynamiq emits JSON-LD with `prov:`, `owl:`, `rdfs:`,
  `skos:`, `xsd:` namespaces. Graphiti does not.
- **JSON-LD** — Dynamiq honors `Accept: application/ld+json`. Graphiti
  has its own JSON shape.
- **OWL/RDFS/SKOS** — Dynamiq renders entity types as `owl:Class`
  with `rdfs:subClassOf` and canonical/aliases as
  `skos:prefLabel/altLabel`. Graphiti does not.
- **MCP** — Dynamiq ships an MCP server (22 tools). Graphiti is REST.

## Permissioning

- Dynamiq: workspace RLS (Postgres-enforced, forced) + sensitivity
  labels + label-policy filter that runs over retrieval results.
  Admin / owner / service principals bypass label policies.
- Graphiti: caller-supplied scope. The library leaves the question
  of who can see which fact to the embedding application.

## Provenance

- Dynamiq: every state change opens a `prov_activity` row with
  `agent_kind` ∈ {llm, user, system} + `agent_ref`. Activities can be
  linked to upstream activities via `prov_activity_derivation`. The
  attach-evidence action writes a `revised` link from its activity
  back to the edge's original activity.
- Graphiti: tracks the source episode that produced a fact, plus the
  LLM that judged it. No activity lineage between agents.

## Agent surface

- Dynamiq: 22 MCP tools (search, get_fact, add_fact, add_episode,
  get_provenance, graph_query, as_of_query, assign_label,
  invoke_action, propose/approve/reject_proposal, …). Tools are
  declared with JSON Schema and discoverable.
- Graphiti: Python SDK + REST. No MCP.

## License

- Dynamiq: TBD (contact maintainer).
- Graphiti: Apache 2.0. Zep Cloud (the managed product) is
  commercial.

## When to pick which

**Pick Zep / Graphiti if** you want a mature managed cloud, the Neo4j
operational story works for you, and you don't need MCP or PROV-O.

**Pick Dynamiq if** you need audit-grade provenance, want everything
in Postgres, run MCP-native agents, or need per-fact sensitivity
labels for compliance.
