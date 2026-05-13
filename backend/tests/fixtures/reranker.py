"""Reranker stub helper.

Phase G5 ships a cross-encoder reranker that's off by default. Scenario
tests that want to assert "rerank actually reordered the candidates"
should NOT pull the real sentence-transformers model — instead they
inject a deterministic stub.

Usage::

    def test_my_thing(stub_reranker):
        stub_reranker.set(lambda q, ps: [1.0 / (i + 1) for i, _ in enumerate(ps)])
        ...

The fixture restores the original ``rerank._score_fn`` on teardown.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from app.retrieval import rerank


@dataclass
class _StubHandle:
    def set(
        self,
        fn: Callable[[str, list[str]], list[float]] | None = None,
    ) -> None:
        if fn is None:
            def fn(_q: str, passages: list[str]) -> list[float]:
                return [1.0 / (i + 1) for i, _ in enumerate(passages)]
        rerank.set_score_fn(fn)


@pytest.fixture
def stub_reranker():
    handle = _StubHandle()
    yield handle
    rerank.set_score_fn(None)
