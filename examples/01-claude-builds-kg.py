"""Drive a real Claude agent against the Dynamiq MCP server.

Pre-reqs:
- ``make up`` is running locally (backend on :8000).
- ``ANTHROPIC_API_KEY`` is exported.
- An agent token has been minted in the web UI for some workspace;
  export ``DYNAMIQ_TOKEN`` with the ``mem_…`` value.

Run::

    pip install anthropic httpx
    python 01-claude-builds-kg.py

The script will:
1. List the platform's MCP tool surface.
2. Hand Claude a short prompt asking it to record three facts about
   Anthropic.
3. Stream Claude's tool calls, invoking each one against the local
   backend.
4. Query the resulting fact back via ``get_fact`` and print it.
"""
from __future__ import annotations

import json
import os
import sys

import anthropic
import httpx


API_URL = os.environ.get("DYNAMIQ_API_URL", "http://localhost:8000")
TOKEN = os.environ.get("DYNAMIQ_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5")

if not TOKEN:
    sys.exit(
        "DYNAMIQ_TOKEN is required — mint an agent token in the web UI and "
        "export it as DYNAMIQ_TOKEN=mem_…"
    )
if not ANTHROPIC_KEY:
    sys.exit("ANTHROPIC_API_KEY is required")


def _mcp(payload: dict) -> dict:
    """Invoke an MCP tool over the JSON-RPC endpoint."""
    response = httpx.post(
        f"{API_URL}/api/mcp/rpc",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": payload},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json().get("result", {})


def main() -> None:
    # 1. Pull the tool list from the platform so Claude has the same
    # input_schema definitions the server will validate against.
    list_response = httpx.post(
        f"{API_URL}/api/mcp/rpc",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        timeout=15.0,
    )
    list_response.raise_for_status()
    tools_raw = list_response.json()["result"]["tools"]
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in tools_raw
    ]
    print(f"loaded {len(tools)} MCP tools")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                "Use the MCP tools to record three short factual claims "
                "about Anthropic the AI company. Land them via `add_fact` "
                "after creating any entities you need. Keep facts concise "
                "and grounded in widely-known public information."
            ),
        }
    ]

    for _ in range(12):
        response = client.messages.create(
            model=MODEL, max_tokens=2048, tools=tools, messages=messages
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if text_blocks:
            print("\n[assistant]", "\n".join(text_blocks))

        assistant_msg = {"role": "assistant", "content": []}
        for t in text_blocks:
            assistant_msg["content"].append({"type": "text", "text": t})
        for tu in tool_uses:
            assistant_msg["content"].append(
                {"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input}
            )
        messages.append(assistant_msg)
        if not tool_uses:
            break

        tool_results = []
        for tu in tool_uses:
            print(f"\n[tool_call] {tu.name}({json.dumps(tu.input)[:200]})")
            result = _mcp({"name": tu.name, "arguments": tu.input or {}})
            print(f"[tool_result] {json.dumps(result)[:200]}")
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    print("\ndone.")


if __name__ == "__main__":
    main()
