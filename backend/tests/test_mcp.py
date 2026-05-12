"""Minimal MCP tool-registry sanity checks (no LLM calls)."""
from __future__ import annotations

from app.api.mcp.tools import TOOLS, TOOLS_BY_NAME


def test_registry_contains_core_tools():
    required = {
        "search_memory", "get_entity", "graph_query",
        "add_fact", "invalidate_fact", "add_episode",
        "update_entity", "ontology_describe",
        "create_entity_type", "create_relation_type",
        "propose_ontology", "as_of_query",
    }
    assert required.issubset(TOOLS_BY_NAME.keys())
    assert len(TOOLS) == len(TOOLS_BY_NAME)


def test_every_tool_exposes_json_schema():
    for t in TOOLS:
        schema = t.input_schema.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema
