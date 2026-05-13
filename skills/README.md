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
| [agent-to-agent-provenance](agent-to-agent-provenance/SKILL.md) | Cite an upstream agent's activity when deriving a fact. |
| [governance-labels](governance-labels/SKILL.md) | Apply `pii`, `public`, or custom labels; understand policy drop. |
| [action-invocation](action-invocation/SKILL.md) | Invoke a kinetic action (`attach_evidence_to_fact`) with idempotency. |
| [time-travel-queries](time-travel-queries/SKILL.md) | Ask "what did we believe at time T?" via `as_of_query`. |
| [reviewing-pending-facts](reviewing-pending-facts/SKILL.md) | Walk the proposals queue: approve / reject / supersede. |

## MCP tool ↔ skill matrix

```
search_memory          → querying-with-confidence, time-travel-queries
get_fact               → querying-with-confidence
add_fact               → ingesting-facts, agent-to-agent-provenance
add_episode            → ingesting-facts
get_provenance         → querying-with-confidence, agent-to-agent-provenance
graph_query            → time-travel-queries
as_of_query            → time-travel-queries
assign_label           → governance-labels
list_labels            → governance-labels
invoke_action          → action-invocation
list_proposals         → reviewing-pending-facts
approve_proposal       → reviewing-pending-facts
reject_proposal        → reviewing-pending-facts
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
