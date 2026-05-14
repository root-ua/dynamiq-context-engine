# Dynamiq agent skills

Drop these into any Claude Code (or Anthropic SDK harness) that
has the Dynamiq MCP server registered. Each skill is one markdown
file with a frontmatter block describing **when** to invoke it and
**which** MCP tools it touches.

## Installation

### Claude Code

```bash
# from the repo root
mkdir -p ~/.claude/skills
cp -r skills/* ~/.claude/skills/
```

Restart Claude Code. Each `<skill-name>/SKILL.md` becomes a
discoverable skill that the model will invoke when its frontmatter
triggers match the user's request.

### Anthropic SDK

Build the harness file from the `SKILL.md` files and pass it as a
system prompt. Each skill body is self-contained.

## Catalog

| Skill | When |
|---|---|
| [querying-with-confidence](querying-with-confidence/SKILL.md) | One decision-grade fact (revenue, head count, KPI) with confidence + freshness. |
| [ingesting-facts](ingesting-facts/SKILL.md) | Push a fact or episode in — choose `add_fact` (atomic) vs `add_episode` (text → extraction). |
| [document-ingestion](document-ingestion/SKILL.md) | Land facts from a PDF / image / markdown — the agent reads the file, the platform owns the graph. |
| [graph-traversal](graph-traversal/SKILL.md) | Walk the typed property graph from a seed entity (`graph_query`) or fetch a single entity's neighborhood (`get_entity`). |
| [ontology-management](ontology-management/SKILL.md) | Inspect the workspace's ontology; extend it with `create_entity_type` / `create_relation_type` / `propose_ontology`. |
| [agent-to-agent-provenance](agent-to-agent-provenance/SKILL.md) | Cite an upstream agent's activity when deriving a fact; read provenance with `get_provenance`. |
| [governance-labels](governance-labels/SKILL.md) | Apply `pii`, `public`, or custom labels; understand policy drop. |
| [action-invocation](action-invocation/SKILL.md) | Invoke a kinetic action (`attach_evidence_to_fact`) with idempotency. |
| [time-travel-queries](time-travel-queries/SKILL.md) | Ask "what did we believe at time T?" via `as_of_query`. |
| [reviewing-pending-facts](reviewing-pending-facts/SKILL.md) | Walk the proposals queue: approve / reject; audit with `list_action_invocations`. |
| [connecting-from-external-agent](connecting-from-external-agent/SKILL.md) | Bootstrap Claude Code / Cursor / Claude Desktop / Claude Web / OpenAI Agents SDK against a Dynamiq workspace. |

## MCP tool ↔ skill matrix

Every MCP tool the server exposes, with its primary skill (and the
supporting skills that also reference it).

```
search_memory             → querying-with-confidence, graph-traversal,
                            time-travel-queries, ingesting-facts
get_fact                  → querying-with-confidence
get_entity                → graph-traversal
graph_query               → graph-traversal, time-travel-queries
as_of_query               → time-travel-queries
add_fact                  → ingesting-facts, agent-to-agent-provenance
add_episode               → ingesting-facts, document-ingestion
update_entity             → ingesting-facts (corrections section)
invalidate_fact           → ingesting-facts (corrections section)
get_provenance            → agent-to-agent-provenance, querying-with-confidence
ontology_describe         → ontology-management
create_entity_type        → ontology-management
create_relation_type      → ontology-management
propose_ontology          → ontology-management
assign_label              → governance-labels
list_labels               → governance-labels
list_action_types         → action-invocation
execute_action            → action-invocation
list_action_invocations   → action-invocation, reviewing-pending-facts
list_proposals            → reviewing-pending-facts
approve_proposal          → reviewing-pending-facts
reject_proposal           → reviewing-pending-facts
bulk_approve_proposals    → reviewing-pending-facts (validator agent)
bulk_reject_proposals     → reviewing-pending-facts (validator agent)
```

## Adding a skill

Create `<short-kebab-name>/SKILL.md` with frontmatter:

```yaml
---
name: <short-kebab-name>
description: |
  One paragraph. The model uses this to decide whether to invoke.
triggers:
  - "phrasings that should fire this"
mcp_tools:
  - tool_name
  - other_tool
---
```

Body covers: when to call vs not, the exact tool arguments, fall-back
patterns, and one short example. Link related skills with regular
markdown links.
