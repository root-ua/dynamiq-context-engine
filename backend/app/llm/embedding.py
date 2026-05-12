"""Embedding client wrapping LiteLLM's aembedding endpoint."""
from __future__ import annotations

from collections.abc import Sequence

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings


class EmbeddingClient:
    def __init__(self, provider: str | None = None, model: str | None = None, dim: int | None = None) -> None:
        settings = get_settings()
        self.provider = provider or settings.embedding_provider
        self.model = model or settings.embedding_model
        self.dim = dim or settings.embedding_dim

    @property
    def model_id(self) -> str:
        if "/" in self.model:
            return self.model
        return f"{self.provider}/{self.model}"

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((litellm.APIConnectionError, litellm.APIError, litellm.Timeout)),
    )
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [t.strip() or " " for t in texts]
        response = await litellm.aembedding(model=self.model_id, input=cleaned)
        return [row["embedding"] for row in response["data"]]

    async def embed_one(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0]


_default_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _default_client
    if _default_client is None:
        _default_client = EmbeddingClient()
    return _default_client
