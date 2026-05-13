"""Smoke test for the playground SSE route.

We don't make a real Anthropic call here (covered by the live_llm
suite); instead we patch ``anthropic.AsyncAnthropic`` with a stub
client that emits one text block and one tool_use block, and assert
that the SSE stream carries through the expected event sequence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.api.rest import playground as playground_mod

pytestmark = pytest.mark.skipif(
    playground_mod.anthropic is None,
    reason="anthropic SDK not installed; playground route is opt-in",
)


@dataclass
class _Block:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None


@dataclass
class _Response:
    content: list[_Block]


class _StubMessages:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **_: Any) -> _Response:
        self.calls += 1
        if self.calls == 1:
            return _Response(
                content=[
                    _Block(type="text", text="Looking up ontology…"),
                    _Block(
                        type="tool_use",
                        id="toolu_1",
                        name="ontology_describe",
                        input={},
                    ),
                ]
            )
        return _Response(
            content=[_Block(type="text", text="Done — workspace has types.")]
        )


class _StubClient:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.messages = _StubMessages()


@pytest.fixture
def patched_anthropic(monkeypatch):
    monkeypatch.setattr(playground_mod.anthropic, "AsyncAnthropic", _StubClient)
    monkeypatch.setattr(
        playground_mod, "_tool_definitions", lambda: [], raising=True
    )
    from app.core.config import Settings

    def _settings():
        s = Settings()
        object.__setattr__(s, "anthropic_api_key", "test-key")
        return s

    monkeypatch.setattr(playground_mod, "get_settings", _settings)
    yield


@pytest.mark.asyncio
async def test_playground_run_loop_emits_expected_event_sequence(
    enterprise_workspace, patched_anthropic
):
    """``_run_loop`` should yield text_delta → tool_call →
    tool_result → done, in that order, for a single-tool-use response."""
    e = enterprise_workspace
    from app.auth.jwt import Principal
    from app.db.session import session_scope

    principal = Principal(
        user_id=e.alice.id, email=e.alice.email,
        workspace_id=e.workspace_id, role="editor",
        claims={}, kind="user",
    )

    import json as _json
    events: list[dict[str, Any]] = []
    async with session_scope(
        workspace_id=e.workspace_id, user_id=e.alice.id
    ) as session:
        async for event in playground_mod._run_loop(
            session=session,
            workspace_id=e.workspace_id,
            actor_id=e.alice.id,
            principal=principal,
            model="claude-haiku-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": "list types"}],
        ):
            events.append(_json.loads(event["data"]))

    types_seen = [e["type"] for e in events]
    assert "text_delta" in types_seen
    assert "tool_call" in types_seen
    assert "tool_result" in types_seen
    assert types_seen[-1] == "done"
