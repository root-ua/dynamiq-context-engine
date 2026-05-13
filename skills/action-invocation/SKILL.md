---
name: action-invocation
description: |
  Use when an agent needs to invoke a registered kinetic action
  (e.g. ``attach_evidence_to_fact``) — the platform's safe write-back
  surface with idempotency, role gates, and optional human approval.
triggers:
  - "attach this evidence to the fact"
  - "run the action X on Y"
  - "invoke <action_type>"
mcp_tools:
  - list_action_types
  - invoke_action
  - get_action_invocation
---

# Action invocation

## The shape

A **kinetic action** is a server-side function the workspace owner
opted in to. It's not arbitrary code execution — each action declares
its input schema, its required role (`viewer` / `editor` / `admin`),
and whether it needs explicit approval.

The currently-shipped action is `attach_evidence_to_fact` — it
appends an evidence record to an edge's `props.evidence` and writes
an audit row + PROV-O derivation link from the action's activity to
the edge's original activity.

## Listing actions

```json
{"tool": "list_action_types", "arguments": {}}
```

Returns the available `action_type` rows with their input schemas. If
the action you need isn't here, the workspace doesn't have it
registered — don't try to call it.

## Invoking with idempotency

```json
{
  "tool": "invoke_action",
  "arguments": {
    "action_type": "attach_evidence_to_fact",
    "input": {
      "edge_id": "<edge_id>",
      "episode_id": "<episode_id>",
      "comment": "Confirmed in the Q3 review doc."
    },
    "idempotency_key": "<stable-uuid-the-agent-picked>"
  }
}
```

Pass an `idempotency_key` you control (uuid4 is fine). If the same
key is used twice, the platform returns the first invocation's
result; it does not run the action twice. This is the safe pattern
for retry loops.

## Approval-gated actions

Some action types are marked `requires_approval`. In that case the
first call returns `{"status": "pending_approval", "invocation_id":
"..."}`. A human approver hits the UI; once approved, the platform
runs the handler and `get_action_invocation` returns the result.

## Don't

- Don't poll `get_action_invocation` more than once a second. The
  rate limiter (`MCP_RATE_LIMIT_RPM`) will kick in.
- Don't pass freeform JSON in `input` that doesn't match the action
  type's input schema. The platform rejects with `400` and the agent
  has to retry with the right shape.

Related: [agent-to-agent-provenance](../agent-to-agent-provenance/SKILL.md)
— the action writes its own activity, which becomes upstream
provenance for any fact the action revised.
