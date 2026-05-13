---
name: connecting-from-external-agent
description: |
  Use when a developer or agent needs to set up a Dynamiq workspace
  as an MCP server in their own client (Claude Code, Cursor, Claude
  Desktop, Claude Web's Custom Connectors, OpenAI Agents SDK).
  Covers token minting, snippet selection, smoke-testing, and what
  to do when a token leaks.
triggers:
  - "how do I connect Claude Code to my workspace"
  - "set up Cursor with Dynamiq"
  - "add Dynamiq as an MCP server"
  - "my token leaked, what now"
mcp_tools: []
---

# Connecting an external agent to a Dynamiq workspace

## The flow

1. **Mint a token.** Open `/[workspace]/settings/agents` in the web
   UI and click **Create token**. Pick a name ("Alice's Claude Code"
   is fine) and a kind:
   - **service** — workspace-bound, doesn't act as a specific user.
     Right for shared CI / bot use cases.
   - **user** — acts as you. Right for "this is my personal token in
     my personal client". Inherits your role + sensitivity-label
     bypass.
2. **Copy the plaintext.** The page shows the token exactly once.
   Store it in a password manager.
3. **Paste into your client.** The agents page renders a tab per
   client with a ready-to-copy snippet. URLs and token are
   pre-filled when you've just created one.

## Snippet templates

URLs assume `https://<HOST>` is your deployment. The token format is
`mem_<31-char-body>`.

**Claude Code:**

```bash
claude mcp add-json dynamiq '{"type":"http","url":"https://<HOST>/api/mcp/rpc","headers":{"Authorization":"Bearer mem_…"}}' --scope user
```

Restart Claude Code; tools appear under `/mcp`.

**Cursor** — `~/.cursor/mcp.json` (or per-project `.cursor/mcp.json`):

```jsonc
{
  "mcpServers": {
    "dynamiq": {
      "url": "https://<HOST>/api/mcp/rpc",
      "headers": { "Authorization": "Bearer mem_…" }
    }
  }
}
```

**Claude Desktop** — `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "dynamiq": {
      "transport": "http",
      "url": "https://<HOST>/api/mcp/rpc",
      "headers": { "Authorization": "Bearer mem_…" }
    }
  }
}
```

**Claude Web Custom Connectors:**
- Open claude.ai → Settings → Connectors → Add custom connector.
- URL: `https://<HOST>/api/mcp/rpc`
- Auth: Bearer `mem_…`
- Save. Claude lists all 22 Dynamiq tools.

**OpenAI Agents SDK:**

```python
from openai import OpenAI
client = OpenAI()
resp = client.responses.create(
    model="gpt-5",
    tools=[{
        "type": "mcp",
        "server_label": "dynamiq",
        "server_url": "https://<HOST>/api/mcp/rpc",
        "headers": {"Authorization": "Bearer mem_…"},
    }],
    input="What does our graph say about Acme?",
)
print(resp.output_text)
```

> ChatGPT's "Custom GPTs" use OpenAPI **Actions**, not MCP. Use the
> OpenAI Agents SDK above for an MCP-aware OpenAI flow.

## Smoke-test the connection

Before trusting your client's auto-discovery, verify by hand:

```bash
curl -X POST 'https://<HOST>/api/mcp/rpc' \
  -H 'Authorization: Bearer mem_…' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Expect a JSON body with `result.tools` carrying 22 tool entries
(`search_memory`, `get_fact`, `add_fact`, …). A 401 means the token
is rejected; a 200 with empty tools means the scope was misset (very
unlikely — `mcp` is the default).

## When a token leaks

1. Go to `/[workspace]/settings/agents`.
2. Click **Rotate** next to the leaked token. The platform mints a
   new token with the same name, scopes, kind, and expiry; the old
   one is revoked atomically.
3. Update the snippet in your client.

If you need a tombstone-only revocation (e.g. you're decommissioning
a tool), click **Revoke** instead.

## Rate limits

By default each token is capped at 60 requests/minute on `/api/mcp/*`
(`MCP_RATE_LIMIT_RPM`). Bursting past it returns a 429 with
`Retry-After`. Increase the cap via env if your client has a higher
sustained tool-call rate.

Related: [governance-labels](../governance-labels/SKILL.md) if your
client should respect label policies; [agent-to-agent-provenance](../agent-to-agent-provenance/SKILL.md)
when one external agent's writes will be cited by another.
