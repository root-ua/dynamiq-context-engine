---
name: time-travel-queries
description: |
  Use when an agent needs to know what the graph *believed* at a
  past time, not what it knows now. Bi-temporal: both ``valid_time``
  (when the fact was true in the world) and ``sys_time`` (when the
  system believed it) are queryable.
triggers:
  - "as of <date>"
  - "what did we know on <date>"
  - "before X happened"
  - "rewind the graph to <date>"
mcp_tools:
  - as_of_query
  - get_fact
  - graph_query
  - search_memory
---

# Time-travel queries

## Two axes

- **`valid_time`** — when the fact was true in the world. "Alice
  worked at Acme from 2020-01 to 2024-06."
- **`sys_time`** — when the system believed the fact. "We *recorded*
  on 2024-08-14 that Alice worked at Acme."

Most user questions only care about `valid_time`. `sys_time` shows up
when you need to audit "what did the system show on this date?"
(e.g. for a finance disclosure).

## Asking "what was true at time T?"

`get_fact` accepts `as_of`:

```json
{
  "tool": "get_fact",
  "arguments": {
    "subject": "<id>", "predicate": "works_at",
    "as_of": "2023-05-01T00:00:00Z"
  }
}
```

Returns the fact whose `valid_time` range contained that timestamp.

For multiple facts in a window:

```json
{
  "tool": "as_of_query",
  "arguments": {
    "valid_at": "2023-05-01T00:00:00Z",
    "subject_id": "<id>",
    "predicate": "works_at"
  }
}
```

## Asking "what did we believe on system date T?"

Add `sys_at`:

```json
{
  "tool": "as_of_query",
  "arguments": {
    "valid_at": "2023-05-01T00:00:00Z",
    "sys_at": "2024-08-15T00:00:00Z"
  }
}
```

This is the "what did our records show on August 15, 2024 about May
1, 2023?" query. If the system later learned the fact was wrong
(invalidate + re-add), `sys_at` lets you see the prior belief.

## Time-travelling a search

`search_memory` accepts `as_of_valid` and `as_of_sys`:

```json
{
  "tool": "search_memory",
  "arguments": {
    "query": "platform lead",
    "as_of_valid": "2024-12-01T00:00:00Z",
    "include_kinds": ["edge"]
  }
}
```

This is how you answer "who was the platform lead at year-end 2024?"
even if they've since left the role.

## Don't

- Don't pass an `as_of` in the future. The platform won't error, but
  the result is empty since no `valid_time` range extends past `now`
  for ongoing facts unless explicitly authored.
- Don't confuse `sys_time` with `created_at`. `sys_time` is the
  bi-temporal range, `created_at` is a single timestamp. The closure
  semantics differ.

Related: [querying-with-confidence](../querying-with-confidence/SKILL.md)
— `get_fact` is the right tool 90% of the time; reach for
`as_of_query` only when you need the multi-row shape.
