---
name: reviewing-pending-facts
description: |
  Use when an agent needs to walk the proposals queue — facts that
  landed below the workspace's confidence threshold or hit a
  high-stakes contradiction. Approve, reject, or supersede.
triggers:
  - "review pending facts"
  - "approve the next proposal"
  - "what's in the review queue"
mcp_tools:
  - list_proposals
  - approve_proposal
  - reject_proposal
  - get_provenance
---

# Reviewing pending facts

## What lands here

The proposals queue (`pending_fact` table) collects edges that didn't
land live, for two reasons:

1. **Low confidence.** The workspace's `extraction_policy` row for
   this predicate has `min_confidence` higher than the extraction's
   stated confidence. The fact is held until a human / agent approves.
2. **High-stakes contradiction.** The predicate is `high_stakes` (a
   property in the ontology) and a contradicting live fact already
   exists. The new fact is held until a human resolves.

## Walking the queue

```json
{
  "tool": "list_proposals",
  "arguments": {"status": "pending", "limit": 20}
}
```

Each entry carries the proposed subject / predicate / object, the
confidence, the source episode id, and the reason (`min_confidence`
or `high_stakes_contradiction`).

For high-stakes contradictions, fetch the current live fact's
provenance first so you know what's being contradicted:

```json
{"tool": "get_provenance", "arguments": {"edge_id": "<live_edge_id>"}}
```

## Approving

```json
{
  "tool": "approve_proposal",
  "arguments": {"proposal_id": "<id>", "comment": "Confirmed via review doc."}
}
```

The platform materialises the edge, closes any contradicting live
fact (cardinality-one) at the new `valid_from`, and writes both an
`approve` audit row and a `prov_activity` for the approval.

If the source episode was deleted in the meantime, `approve_proposal`
refuses with `source_episode_missing` — surface that to the user
rather than blindly retrying.

## Rejecting

```json
{
  "tool": "reject_proposal",
  "arguments": {"proposal_id": "<id>", "comment": "Source unreliable."}
}
```

Marks the proposal as `rejected`. The fact never lands as an edge.

## Don't

- Don't bulk-approve a category without spot-checking. Low-confidence
  extractions exist for a reason; approving every one defeats the
  threshold gate.
- Don't approve a proposal whose source episode you can't see. The
  proposal is showing because the original write was ACL-scoped; you
  approving it on a different principal would expose data to people
  who shouldn't see it.

Related: [governance-labels](../governance-labels/SKILL.md) — labels
on a pending proposal carry through to the approved edge.
