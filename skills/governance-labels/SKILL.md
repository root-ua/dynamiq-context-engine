---
name: governance-labels
description: |
  Use when an agent needs to apply or interpret sensitivity labels
  (``pii``, ``public``, ``confidential``, custom slugs) on facts /
  episodes / entities. Includes the rules around policy drop and
  admin bypass.
triggers:
  - "mark this as PII"
  - "tag this fact as confidential"
  - "why didn't I see X in the results"
mcp_tools:
  - list_labels
  - assign_label
  - unassign_label
  - search_memory
---

# Governance labels

## The two-layer model

1. **Workspace RLS.** Postgres-enforced. Only members of a workspace
   see its rows. No agent code path can bypass this.
2. **Sensitivity labels + policy.** Layered on top. Labels are
   per-fact (or per-episode / per-entity) tags. A policy is a rule
   that fires on the labels (e.g. "if `pii` AND `public` are both
   assigned → drop").

Admin / owner / service principals **bypass policy** (not RLS). The
admin still has to be a workspace member to see anything; once in,
they see all rows regardless of label policy.

## Assigning a label

```json
{
  "tool": "assign_label",
  "arguments": {
    "target_kind": "edge",
    "target_id": "<edge_id>",
    "label_slug": "pii"
  }
}
```

`target_kind` is one of `edge`, `episode`, `entity`. Labels are not
predicate-bound — they describe the *content*, not the relation.

## Discovering labels in a workspace

```json
{"tool": "list_labels", "arguments": {}}
```

Returns every label slug with description + the policies that
reference it. Use this before inventing a new slug — many workspaces
already have one for what you want.

## Reading why a result was dropped

`search_memory` returns hits with `policy_warnings` in the payload
when a label policy was on the edge of firing but didn't (e.g. the
agent's role bypassed it). Surface those warnings to the user so they
know the fact carries a sensitivity tag even when the agent could see
it.

## Don't

- Don't assign `public` to a fact that contains an email or phone
  number. The policy is `mutually_exclusive` with `pii` — you'll
  cause the fact to be dropped from every editor's view.
- Don't assume admin bypass means "no audit". Every label assignment
  is audit-logged.
- Don't invent label slugs. Add them in the ontology UI / via the
  label-management API first; otherwise `assign_label` errors out.

Related: [reviewing-pending-facts](../reviewing-pending-facts/SKILL.md)
— labels on pending facts carry through to the approved edge.
