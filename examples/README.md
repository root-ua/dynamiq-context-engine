# Examples

Standalone scripts that exercise the platform end-to-end. Run from
the repo root with the backend stack up (`make up`).

## Setup

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and (optionally) OPENAI_API_KEY.
make up                # backend + worker + web running locally
cd examples
# Pick an example below.
```

## Catalog

### `01-claude-builds-kg.py`

A 30-line script: ask Claude (haiku) to land three facts about
Anthropic via our MCP tools, then query one back.

Mirrors `backend/tests/test_scenario_live_llm.py`. Useful as a sanity
check on a fresh install — run after `make up` and you'll know within
a minute whether the whole stack (auth → MCP → extraction → live
Claude → write-back) works.

```bash
cd examples
python -m venv .venv && source .venv/bin/activate
pip install anthropic httpx
python 01-claude-builds-kg.py
```

Expected output: a short transcript of tool calls, then the final
`get_fact` result printed as JSON.
