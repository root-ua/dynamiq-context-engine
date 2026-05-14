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
  - bulk_approve_proposals
  - bulk_reject_proposals
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
confidence, the source episode id, the reason (`min_confidence`
or `high_stakes_contradiction`), and a triage bundle:

- `proposer_kind` (`llm` / `user` / `system`) and `proposer_agent_ref`
  (model name for `llm`; user id for `user` / `system`).
- `proposer_email` when the proposer has an `app_user` row.
- `source_episode_snippet` (first 200 chars of the source content)
  so you can spot misextractions without a second tool call.
- `upstream_activity_ids` — every activity this proposal cites via
  `prov_activity_derivation` (`derived` or `quoted`). Long chains
  with anonymous links are a smell.
- `triggered_by_user_id` — when the source was an episode, the user
  whose API call enqueued it.

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

## Auditing what got materialised

After approve/reject, the platform writes an `audit_log` row + a
`prov_activity` row. The downstream view: was this edge actually
modified by an action later? Use `list_action_invocations` for that
audit trail:

```json
{
  "tool": "list_action_invocations",
  "arguments": {"status": "completed"}
}
```

Returns every kinetic-action run in the workspace with its input,
result, and the activity id you can follow via `get_provenance`.
Useful when reconciling "I approved this fact yesterday, who else
touched it?".

## Validator agent: map-reduce triage

The expected production pattern: many "miner" agents propose facts
in parallel from disparate sources; one "validator" agent (with
read access across the same systems and write access to the
proposals queue) consolidates them.

The validator workflow:

1. `list_proposals({"status": "pending", "limit": 50})` — gets the
   enriched batch in one call.
2. Group by `proposer_kind` + `proposer_agent_ref` to see who's
   pushing what. Several miners independently surfacing the same
   triple is a positive signal — the platform also records this
   automatically (see `dce:endorsementCount` on the edge's
   `get_provenance` once approved).
3. For each row, check the `source_episode_snippet` — does the
   proposed fact actually match the source text? Catches LLM
   hallucinations cheaply.
4. Walk `upstream_activity_ids` on suspicious rows via
   `get_provenance` — long anonymous chains are a smell.
5. Batch the verdict:

```json
{
  "tool": "bulk_approve_proposals",
  "arguments": {
    "ids": ["<id1>", "<id2>", "..."],
    "comment": "validator: confirmed against 2024-Q3 ledger"
  }
}
```

```json
{
  "tool": "bulk_reject_proposals",
  "arguments": {
    "ids": ["<idN>"],
    "reason": "validator: snippet doesn't support claim"
  }
}
```

Both tools cap at 500 ids per call and return per-id results with
`approved_count` / `rejected_count` + `failed_count`. A failure
(missing proposal, source episode deleted, already reviewed) on one
id doesn't abort the batch — you'll see `ok: false, error: "..."`
in `results` for that row.

## Don't

- Don't bulk-approve a category without spot-checking. Low-confidence
  extractions exist for a reason; approving every one defeats the
  threshold gate.
- Don't approve a proposal whose source episode you can't see. The
  proposal is showing because the original write was ACL-scoped; you
  approving it on a different principal would expose data to people
  who shouldn't see it.
- Don't treat a high endorsement count as proof. Endorsements record
  agreement; they don't validate accuracy — agents can be wrong in
  the same way.

Related: [governance-labels](../governance-labels/SKILL.md) — labels
on a pending proposal carry through to the approved edge.
