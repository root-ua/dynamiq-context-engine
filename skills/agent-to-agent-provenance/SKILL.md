---
name: agent-to-agent-provenance
description: |
  Use when one agent (a meta-agent, reviewer, analyst) writes a fact
  derived from another agent's prior work. Records a W3C PROV-O
  ``wasDerivedFrom`` link so the next caller can walk the chain.
triggers:
  - "based on the previous agent's finding"
  - "summarize what agent X said about Y"
  - "I'm revising what we previously thought about X"
mcp_tools:
  - add_fact
  - add_episode
  - get_provenance
---

# Agent-to-agent provenance

## The pattern

When agent A wrote a fact and agent B writes a derived fact citing
A's work, B passes A's activity id into the
``derived_from_activity_ids`` array. The platform records a row in
``prov_activity_derivation`` linking B's activity to A's. Later,
``get_provenance(edge_b_id)`` walks the chain and emits both
activities as ``wasDerivedFrom`` nodes in the JSON-LD bundle.

## Getting agent A's activity id

```json
{
  "tool": "get_provenance",
  "arguments": {"edge_id": "<edge_a_id>"}
}
```

Response:

```json
{
  "@id": "dce:edge/...",
  "wasGeneratedBy": {
    "@id": "dce:activity/<a_activity_id>",
    "wasAssociatedWith": {"@id": "dce:agent/llm/claude-sonnet-4-6"}
  }
}
```

Extract `<a_activity_id>` from the `@id` (strip the `dce:activity/`
prefix).

## Writing the derived fact

```json
{
  "tool": "add_fact",
  "arguments": {
    "subject": "<entity_id>",
    "predicate": "<relation_slug>",
    "object": "<entity_id>",
    "fact": "<revised statement>",
    "derived_from_activity_ids": ["<a_activity_id>"]
  }
}
```

You may pass multiple upstream activity ids if the new fact draws on
several prior activities.

## Why this matters

Auditors looking at the new fact see the chain in one query:

```json
{
  "wasGeneratedBy": {"@id": "dce:activity/B"},
  "wasDerivedFrom": [
    {"@id": "dce:episode/..."},
    {"@id": "dce:activity/A"}
  ]
}
```

Without the link, B's mutation looks like a fresh assertion — there's
no trace of which prior agent's work it built on.

## Don't

- Don't fake a self-link (`derived_activity_id ==
  upstream_activity_id`). The DB rejects it with a CHECK constraint.
- Don't pass `derived_from_activity_ids` on a fact you came up with
  independently. It pollutes the audit trail.

Related: [reviewing-pending-facts](../reviewing-pending-facts/SKILL.md)
when an agent revises a previously approved proposal — set
`derivation_kind: "revised"` in that case.
