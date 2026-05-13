---
name: ingesting-facts
description: |
  Use when an agent has new information to write into the graph.
  Picks between ``add_fact`` (atomic, subject-predicate-object triple
  the agent is confident about) and ``add_episode`` (free-form text
  that the extraction pipeline will parse into entities + edges).
triggers:
  - "record that X"
  - "save the fact that X"
  - "remember that X"
  - "ingest the following note"
mcp_tools:
  - add_fact
  - add_episode
  - propose_fact
---

# Ingesting facts

## Pick the right tool

| You have | Use |
|---|---|
| A discrete triple ("Alice works at Acme") with the subject + object IDs already resolved. | `add_fact` |
| A paragraph of unstructured text. | `add_episode` (extraction will parse it). |
| A discrete triple but you're not confident enough to land it live. | `propose_fact` (routes to the review queue). |

`add_fact` returns the edge atomically — useful when the agent has
already done its own NER and is just landing the result. `add_episode`
returns an episode id and queues the extraction worker; expect the
edges to appear ~1–5s later.

## `add_fact`

```json
{
  "tool": "add_fact",
  "arguments": {
    "subject": "<entity_id>",
    "predicate": "<relation_slug>",
    "object": "<entity_id>",
    "fact": "Alice works at Acme",
    "valid_from": "2025-01-15T00:00:00Z",
    "valid_to": null,
    "confidence": 0.95
  }
}
```

If the predicate has cardinality-object=one (e.g. `works_at`), the
contradictor will close the prior fact on the same subject at the new
`valid_from`. You don't need to do this yourself.

For high-stakes predicates (the workspace marks some predicates as
`high_stakes` in the ontology), conflicting writes go to the proposals
queue automatically — `add_fact`'s result will be `{"pending_fact_id":
...}` instead of `{"edge": ...}`. Surface that to the user.

## `add_episode`

```json
{
  "tool": "add_episode",
  "arguments": {
    "content": "Q3 OKR review: Bob accepted the platform lead role…",
    "source_kind": "agent",
    "occurred_at": "2026-05-01T15:00:00Z"
  }
}
```

The pipeline will:
1. Embed the text for retrieval.
2. Run an LLM extractor against the workspace's ontology.
3. Resolve / create entities (Tier-1 external refs → Tier-2 trigram →
   Tier-3 LLM).
4. Create edges; `propose_fact` routes low-confidence ones to the
   review queue.

Pass `derived_from_activity_ids` if this episode is itself derived
from another agent's prior activity — see
[agent-to-agent-provenance](../agent-to-agent-provenance/SKILL.md).

## Corrections after the fact

What's already landed sometimes needs fixing. Two surgical tools:

- **`update_entity`** — change canonical name, aliases, summary, or
  props on an existing entity. Validates props against the type's
  JSON Schema; rejects ones that don't match.
- **`invalidate_fact`** — close an edge's `valid_time` and `sys_time`
  windows. The edge isn't deleted (that would break the bi-temporal
  audit trail); it's marked as no-longer-true with a recorded
  `reason`. Subsequent `live_edges` queries skip it; `history`
  still returns it.

Use `invalidate_fact` over `add_fact(... valid_to=now)` when the
fact was simply wrong rather than naturally ending — the audit log
distinguishes the two.

## Don't

- Don't call `add_fact` with hallucinated entity IDs. Always
  `search_memory` or `create_entity` first.
- Don't loop calling `add_fact` for facts that came from the same
  document — one `add_episode` + extraction is cheaper, captures the
  source, and chains provenance correctly.
- Don't push the same episode twice. The platform doesn't dedupe by
  text content; you'll get duplicate extraction activities.
