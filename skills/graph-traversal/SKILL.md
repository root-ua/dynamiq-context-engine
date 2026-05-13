---
name: graph-traversal
description: |
  Use when an agent needs to walk the typed property graph from a
  seed entity — n hops, predicate filters, type filters, optional
  bi-temporal as-of. Picks `graph_query` over `search_memory` when
  the question is structural ("who reports to Alice?") rather than
  lexical ("anything about reorgs?").
triggers:
  - "who works under <person>"
  - "find everything connected to <entity> within N hops"
  - "what does <entity> link to"
  - "trace the dependency chain from X"
mcp_tools:
  - graph_query
  - get_entity
  - search_memory
---

# Graph traversal

## When to traverse the graph vs search

| Question shape | Tool |
|---|---|
| "Who manages Alice?" / "What's Alice's team?" | `graph_query` (1–2 hops from Alice) |
| "Show me anything about the platform reorg" | `search_memory` (lexical hybrid) |
| "Find everything 2 hops out from `Acme`" | `graph_query` with `max_hops=2` |
| "What entities of type `project` is Bob on?" | `graph_query` + `type_slugs=["project"]` |
| "What's the dependency chain rooted at `payments`?" | `graph_query` + `predicate_slugs=["depends_on"]` |

The rule of thumb: if you have a **seed entity ID** and want to walk
edges from it, use `graph_query`. If you have a **phrase** and want
ranked results across kinds (entity / edge / episode / block), use
`search_memory`.

## Calling `graph_query`

```json
{
  "tool": "graph_query",
  "arguments": {
    "seeds": ["<entity_id>", "..."],
    "max_hops": 2,
    "direction": "both",
    "predicate_slugs": ["works_at", "manages"],
    "type_slugs": ["person", "organization"],
    "as_of_valid": "2025-12-31T00:00:00Z",
    "max_nodes": 200
  }
}
```

- `seeds` — one or more entity IDs to walk from. Resolve names to
  IDs first with `search_memory({"query": "<name>", "include_kinds":
  ["entity"]})`.
- `max_hops` — 1, 2, or 3 is the sweet spot. Past 3 the result set
  explodes; the platform caps at `max_nodes`.
- `direction` — `out` (subject → object), `in` (object → subject), or
  `both`. Default is `both`.
- `predicate_slugs` — restrict traversal to specific relation types.
  Optional; omit to walk every relation.
- `type_slugs` — restrict the **terminal** nodes to specific entity
  types. Doesn't change which edges are walked; just which results
  come back. Optional.
- `as_of_valid` — bi-temporal anchor. Walks the graph **as it was**
  at that valid time. Pair with [time-travel-queries](../time-travel-queries/SKILL.md).
- `max_nodes` — hard cap. Default 500.

Response shape:

```json
{
  "nodes": [
    {"id": "...", "type": "person", "canonical": "Alice",
     "iri": "...", "distance": 1}
  ],
  "edges": [
    {"id": "...", "subject_id": "...", "object_id": "...",
     "predicate": "works_at", "fact": "Alice works at Acme",
     "valid_from": "...", "valid_to": null}
  ]
}
```

`distance` on a node is the hop count from the nearest seed.

## `get_entity` for the "tell me about X" path

When the user names a single entity and wants a full picture:

```json
{
  "tool": "get_entity",
  "arguments": {
    "ref": "<entity_id-or-iri-or-canonical>",
    "include_history": true,
    "include_live_edges": true
  }
}
```

Returns the entity row + all currently-live edges with it as subject
or object + (optional) bi-temporal history. Cheaper than a graph
query when you only need one entity's neighborhood at distance 1.

## Examples

**"Who reports to Alice (transitively)?"**
1. `search_memory({"query": "Alice", "include_kinds": ["entity"], "entity_type": "person"})` → resolve to an entity id.
2. `graph_query({"seeds": ["<alice_id>"], "max_hops": 3, "direction": "in", "predicate_slugs": ["manages"]})` — walks against the `manages` predicate looking for everyone Alice manages, transitively up to 3 levels.
3. Filter the resulting nodes by `type == "person"`.

**"What's the platform team working on right now?"**
1. Resolve `platform` to an entity (org or team).
2. `graph_query({"seeds": ["<platform_id>"], "max_hops": 2, "predicate_slugs": ["member_of", "assigned_to"], "type_slugs": ["project", "task"]})`.

## Don't

- Don't traverse 4+ hops without a `max_nodes` cap. The result set
  grows combinatorially.
- Don't pass `predicate_slugs` you didn't first verify with
  `ontology_describe` — typos return zero results silently.
- Don't use `graph_query` to find an entity by name; that's
  `search_memory`'s job.

Related: [querying-with-confidence](../querying-with-confidence/SKILL.md)
for one-fact lookups; [time-travel-queries](../time-travel-queries/SKILL.md)
for `as_of_valid` patterns; [ontology-management](../ontology-management/SKILL.md)
to see what predicates / types exist.
