---
name: ontology-management
description: |
  Use when an agent needs to inspect or extend the workspace's typed
  ontology — entity types, relation types, their domain/range,
  hierarchy, and constraints. Covers when to invent new types vs
  reuse existing ones, and the `ontology_mode` (strict/flexible/auto)
  that gates extraction.
triggers:
  - "what types exist in this workspace"
  - "add a new entity type for X"
  - "create a relation between A and B"
  - "the extractor needs a new type for Y"
mcp_tools:
  - ontology_describe
  - create_entity_type
  - create_relation_type
  - propose_ontology
---

# Ontology management

## The ontology, in 30 seconds

Every workspace ships with a built-in ontology (~13 entity types +
~15 relation types in `seeds/ontology.yaml` — `person`,
`organization`, `project`, `task`, `meeting`, `document`, `note`,
`topic`; relations like `works_at`, `manages`, `assigned_to`,
`depends_on`, `mentions`, `tagged`). Workspaces can extend it.

Each entity type carries:
- A unique slug (lowercase, kebab-case).
- An optional parent type (`extends`) — gives you a subclass
  hierarchy stored as Postgres `ltree`.
- An optional JSON Schema for its `props` field.

Each relation type carries:
- A `domain` entity type and a `range` entity type.
- Cardinality (`one`/`many` on each side).
- Boolean flags: `symmetric`, `transitive`, `temporal`,
  `high_stakes` (gates the contradictor).
- An optional `inverse_of` pointing to the inverse relation.

## `ontology_describe` — catalog first, mutate later

Always start with the catalog. Don't invent slugs without checking
what's there.

```json
{
  "tool": "ontology_describe",
  "arguments": {
    "include_schemas": true
  }
}
```

Returns every type + every relation with full constraints. Cache the
shape mentally and decide whether the question fits.

## `ontology_mode` — strict / flexible / auto

A workspace setting (`workspace.settings.ontology_mode`) controls
what the extractor can do:

- **`strict`** — extraction is rejected if it tries to use a type or
  relation that doesn't exist. Agents must explicitly call
  `create_entity_type` / `create_relation_type` first.
- **`flexible`** — extraction may **propose** a new type when the
  text genuinely doesn't fit an existing one. New types land tagged
  with `proposed_by` in `ui_hints`.
- **`auto`** — extraction freely invents types from content. Highest
  recall, lowest precision.

Check the workspace's mode before deciding whether to call
`create_entity_type` yourself or trust the extractor to do it.

## Creating a new entity type

```json
{
  "tool": "create_entity_type",
  "arguments": {
    "name": "Customer",
    "slug": "customer",
    "extends": "organization",
    "description": "A paying or trialing account.",
    "schema": {
      "type": "object",
      "properties": {
        "arr_usd": {"type": "number", "minimum": 0},
        "tier": {"enum": ["enterprise", "team", "individual"]}
      }
    }
  }
}
```

- `extends` — pass the parent slug. `thing` is the root. Subtype
  queries (`type_ref=organization` matches both `organization` and
  `customer`) work via the ltree hierarchy.
- `schema` — JSON-Schema-2020-12 for the entity's `props`. Validated
  by `pg_jsonschema` at insert time + Pydantic at the API.

## Creating a new relation type

```json
{
  "tool": "create_relation_type",
  "arguments": {
    "name": "Acquired",
    "slug": "acquired",
    "domain": "organization",
    "range": "organization",
    "cardinality_subject": "many",
    "cardinality_object": "one",
    "temporal": true,
    "high_stakes": true,
    "inverse_of": "acquired_by"
  }
}
```

- `high_stakes: true` — write-time contradictor fires when two
  conflicting facts try to land. Use it for things like
  `works_at` (one current employer), `owns` (one owner at a time).
- `temporal: true` — emphasizes that facts have `valid_time`
  ranges. Most relations are temporal in practice.
- `symmetric: true` — predicates like `knows`. The extractor will
  insert the inverse direction too.

## `propose_ontology` — let the LLM draft

For domains you don't recognize (a new industry, vertical, or
project), let the LLM propose a starter ontology:

```json
{
  "tool": "propose_ontology",
  "arguments": {
    "samples": [
      "Acme Pharma launched the Phase II trial of EGF-101 on 2025-09-01...",
      "..."
    ],
    "apply": false
  }
}
```

Returns a proposal: new types + relations + a rationale per item.
Set `apply: true` to commit; otherwise human-review first.

## Don't

- Don't `create_entity_type` without checking `ontology_describe`
  first. You'll create duplicates.
- Don't mark every relation `high_stakes`. The contradictor cost
  scales with how often you write — reserve it for "one true value"
  semantics.
- Don't pass `schema` without testing it against a real example.
  The Pydantic + pg_jsonschema double-gate will reject any insert
  that doesn't validate.

Related: [ingesting-facts](../ingesting-facts/SKILL.md) once the
types exist; [graph-traversal](../graph-traversal/SKILL.md) once
the relations are populated; [reviewing-pending-facts](../reviewing-pending-facts/SKILL.md)
for high-stakes contradiction handling.
