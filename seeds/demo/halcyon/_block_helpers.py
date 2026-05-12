"""Block-construction helpers for the demo documents.

Writing BlockNote JSON inline is unreadable. These helpers produce the
exact shape document_mod.replace_block_tree + _extract_mentions expect.

The seeder passes the resulting blocks straight through. Every helper
returns a dict; inline entity mentions are `M("person.sarah_chen")`.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def _bid() -> str:
    """Stable-ish block id. Blocks don't need cross-run stability within a
    document — the document itself is keyed on its DocumentSeed.key.
    """
    return str(uuid4())


# ---------------------------------------------------------------------------
# Inline nodes
# ---------------------------------------------------------------------------

def T(text: str, **styles: bool) -> dict[str, Any]:
    """Plain text inline node, optionally with marks (bold/italic/etc.)."""
    node: dict[str, Any] = {"type": "text", "text": text, "styles": {}}
    if styles:
        node["styles"] = {k: v for k, v in styles.items() if v}
    return node


def M(entity_key: str, label: str | None = None) -> dict[str, Any]:
    """An @-mention. `entity_key` is resolved to a UUID by the seeder at
    insert time; until then it's a placeholder.
    """
    return {
        "type": "entityMention",
        "props": {
            "entityId": entity_key,  # replaced with UUID by seeder
            "mention_type": "mention",
            "label": label,
        },
    }


def Link(text: str, href: str) -> dict[str, Any]:
    return {
        "type": "text",
        "text": text,
        "styles": {"link": href},
    }


# ---------------------------------------------------------------------------
# Block constructors
# ---------------------------------------------------------------------------

def _block(
    block_type: str,
    content: list[dict[str, Any]],
    *,
    props: dict[str, Any] | None = None,
) -> dict[str, Any]:
    search_text = "".join(
        n.get("text", "") if isinstance(n, dict) else "" for n in content
    )
    return {
        "id": _bid(),
        "parent_block_id": None,
        "position": 0.0,  # filled in by caller via enumerate
        "block_type": block_type,
        "content": content,
        "props": props or {},
        "search_text": search_text,
    }


def H1(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("heading", list(nodes), props={"level": 1})


def H2(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("heading", list(nodes), props={"level": 2})


def H3(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("heading", list(nodes), props={"level": 3})


def P(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("paragraph", list(nodes))


def Bullet(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("bulletListItem", list(nodes))


def Numbered(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("numberedListItem", list(nodes))


def Quote(*nodes: dict[str, Any]) -> dict[str, Any]:
    return _block("paragraph", list(nodes), props={"tone": "quote"})


def Code(text: str, language: str = "text") -> dict[str, Any]:
    return _block(
        "codeBlock",
        [T(text)],
        props={"language": language},
    )


def finalize(blocks: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Stamp positions 0, 1, 2, ... and return a tuple."""
    for i, b in enumerate(blocks):
        b["position"] = float(i)
    return tuple(blocks)
