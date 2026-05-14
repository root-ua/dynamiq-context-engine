---
name: document-ingestion
description: |
  Use when an agent has a document (PDF, image, markdown, plain text)
  and needs to land its facts in the workspace's knowledge graph.
  Covers the read-the-file-yourself flow because the platform does
  NOT parse binaries — extraction is the calling agent's job.
triggers:
  - "ingest this PDF"
  - "extract facts from this document"
  - "read this file and remember what it says"
  - "summarise this and save the key points"
mcp_tools:
  - add_episode
  - add_fact
  - get_provenance
  - search_memory
---

# Document ingestion

## The architectural rule

The Dynamiq platform doesn't parse PDFs / DOCX / images / scanned
forms. It owns the knowledge graph; the calling agent owns
ingestion. That keeps the platform's footprint small and lets you
swap parsers (OCR, layout-aware, table-aware) without touching the
server.

This means: **you, the agent, read the file. You decide what facts
to land. You call `add_episode` (for prose) or `add_fact` (for
discrete triples) to write them.**

## Pick a strategy

| Input | Strategy |
|---|---|
| **PDF you can read natively** (Anthropic Claude reading an HTTP doc block, or Claude Code with `file_read`) | Read the file → call `add_episode` with the extracted text → the worker extracts entities + edges. |
| **A handful of facts you're already sure about** | Skip the episode. Call `add_fact` once per triple. |
| **Image / screenshot** | Read with vision. Decide whether the contents warrant an episode (lots of text, a table) or a few `add_fact` calls (a chart with three numbers). |
| **Long doc + you're already in a Claude session** | One `add_episode` is enough. The pipeline does the rest. |

## `add_episode` — prose path

```json
{
  "tool": "add_episode",
  "arguments": {
    "content": "<the full extracted text>",
    "source_kind": "agent",
    "occurred_at": "2026-05-15T00:00:00Z"
  }
}
```

Returns `{episode: {id, ...}}`. The extraction worker picks it up
within 1–5 seconds. To follow up: call `search_memory({"query":
"<topic from doc>", "include_kinds": ["edge"]})` and check that the
expected facts landed. Or call `get_provenance(edge_id)` on a
specific edge to see the chain back to your episode.

## Mining historical documents: temporal honesty

If you're reading an OLD document — a 2019 board memo, a 2012
contract, an archival LinkedIn snapshot — the date that matters is
the document's date, NOT today.

Two levers control where the fact lands on the `valid_time` axis:

1. **`add_episode.occurred_at`** — pass the document's authoring
   date (publication date, byline, header). When the extraction
   LLM doesn't emit an explicit `valid_from`, the pipeline now
   falls back to this `occurred_at` instead of today.
2. **Explicit `valid_from` in the extracted edge** — if a fact
   inside the doc names its own date ("Alice joined in 2015"),
   that wins over `occurred_at`. The LLM's system prompt teaches
   it to parse and emit explicit dates.

```json
{
  "tool": "add_episode",
  "arguments": {
    "content": "<2019 board memo text>",
    "source_kind": "agent",
    "occurred_at": "2019-03-15T00:00:00Z"
  }
}
```

The resulting facts land at 2019-03-15 on the valid-time axis, not
today — historical queries (`as_of_query(valid_at='2019-06-01')`)
will surface them; current queries (`live_edges`) won't, unless a
later fact extends or replaces them.

**Don't** leave `occurred_at` unset when ingesting historical data —
the platform defaults it to ingestion time, which scribbles today's
date over actual history.

## `add_fact` — atomic-triple path

For pre-resolved facts:

```json
{
  "tool": "add_fact",
  "arguments": {
    "subject": "<entity_id>",
    "predicate": "founded_in",
    "object": "<entity_id>",
    "fact": "Anthropic was founded in 2021",
    "valid_from": "2021-01-01T00:00:00Z"
  }
}
```

You need both entity ids resolved first. Use `search_memory` with
`include_kinds: ["entity"]` to find them; if they don't exist, create
them with `create_entity_type` + a sibling `add_fact` cascade.

## The playground flow

When a user drops a PDF into the playground:

1. The frontend converts the bytes to base64 and hands them to Claude
   as an Anthropic `document` content block. (No platform-side
   parsing.)
2. Claude reads the document natively, decides which facts matter.
3. Claude calls `add_episode` (typically) with a concise summary +
   the most important quoted spans.
4. The extraction worker turns the episode into entities + edges.
5. The user can now ask follow-up questions like "what does this
   document say about X?" and Claude uses `search_memory` /
   `get_fact` to answer with provenance.

## Don't

- **Don't try to upload PDFs through `/api/documents/upload`.** That
  endpoint accepts text/markdown only by design. PDF parsing is your
  job.
- **Don't `add_episode` a 200-page document verbatim.** Break it into
  chapter-sized episodes (each gets its own provenance bundle, and
  the extraction LLM has a context window).
- **Don't `add_fact` something you read in the doc but aren't sure
  about.** Lower the `confidence` parameter so it routes through the
  proposals queue, or call `propose_fact` instead.

Related: [ingesting-facts](../ingesting-facts/SKILL.md) for the
`add_fact` vs `add_episode` decision; [reviewing-pending-facts](../reviewing-pending-facts/SKILL.md)
when low-confidence extractions need a human approver.
