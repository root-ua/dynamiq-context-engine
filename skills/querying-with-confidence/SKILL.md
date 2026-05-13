---
name: querying-with-confidence
description: |
  Use when an agent needs a single decision-grade fact (revenue, head
  count, KPI, current employer of a person) with explicit confidence
  and freshness — not a ranked list of search hits.
triggers:
  - "what's the latest X"
  - "current value of X"
  - "as of today, what is X"
  - "what does Dynamiq think X is"
mcp_tools:
  - get_fact
  - get_provenance
  - search_memory
---

# Querying with confidence

## When to pick `get_fact` over `search_memory`

| User intent | Use |
|---|---|
| "What is Acme's ARR right now?" | `get_fact` |
| "Show me everything we know about Acme." | `search_memory` |
| "Who is Alice's current manager?" | `get_fact` |
| "Find docs that mention reorg." | `search_memory` |

`get_fact` returns **one** canonical value with `confidence`,
`freshness_days`, and the W3C PROV-O bundle attached. `search_memory`
returns a ranked list of hits across entities, edges, episodes, and
blocks; useful for exploration, not for picking a single number.

## Calling `get_fact`

```json
{
  "tool": "get_fact",
  "arguments": {
    "subject": "<entity_id>",
    "predicate": "<relation_slug>",
    "object": "<entity_id-optional>",
    "as_of": "2026-04-01T00:00:00Z",
    "require_min_confidence": 0.85
  }
}
```

Response shape on success:

```json
{
  "edge_id": "...",
  "value": "Bob",
  "confidence": 0.92,
  "freshness_days": 14,
  "label_slugs": ["public"],
  "wasGeneratedBy": {"@type": "Activity", "..."},
  "wasDerivedFrom": [{"@type": "Activity", "..."}]
}
```

Error shapes worth handling:

- `{"error": "not_found"}` — no fact for this subject/predicate pair.
  Don't invent one.
- `{"error": "below_min_confidence"}` — there's a fact but it didn't
  clear the gate the user asked for. Surface the confidence in the
  reply so the user can lower the bar if they want.
- `{"multiple": true, "candidates": [...]}` — several plausible values
  exist (cardinality-many predicate). Show the list; don't pick one
  silently.

## Resolving subject IDs

You usually start with a name, not an ID. Cascade:

1. Try `search_memory({"query": "<name>", "include_kinds": ["entity"]})`.
2. Pick the top hit whose `type` matches what you expect (don't pick
   a `person` entity when the user asked about an `organization`).
3. Pass the resulting ID to `get_fact`.

Skip step 1 if the user already gave you an external ref (email,
slug, wikidata id) — use `search_memory` with the ref or check
`entity_external_ref` if you can.

## Examples

**"What's Anthropic's headcount?"**
1. `search_memory({"query": "Anthropic", "include_kinds": ["entity"]})`
   → pick the `organization` hit.
2. `get_fact({"subject": <id>, "predicate": "head_count"})`
   → `{"value": "350", "confidence": 0.84, "freshness_days": 22}`.
3. Reply: "Anthropic ≈ 350 (confidence 0.84, last updated 22 days ago)."

Related: [time-travel-queries](../time-travel-queries/SKILL.md) for
`as_of`; [governance-labels](../governance-labels/SKILL.md) when the
returned label_slugs include `pii`.
