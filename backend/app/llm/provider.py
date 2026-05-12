"""LiteLLM-based wrapper for chat + structured output.

Env-configurable provider and model; callers get an async client plus a
``structured(...)`` helper that validates responses against Pydantic models.
"""
from __future__ import annotations

import json
from typing import Any, TypeVar

import litellm
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.provider = provider or settings.llm_provider
        self.model = model or settings.llm_model
        # LiteLLM resolves API keys from env; we just ensure common ones are visible.
        if settings.anthropic_api_key:
            litellm.api_key = settings.anthropic_api_key
        if settings.openai_api_key and not litellm.api_key:
            litellm.api_key = settings.openai_api_key

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
    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        response = await litellm.acompletion(
            model=self.model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        return content

    async def structured(
        self,
        *,
        schema: type[T],
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int | None = 2048,
    ) -> T:
        """Call the model with a JSON-Schema-constrained response and parse it."""
        json_schema = schema.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": _strip_for_openai(json_schema),
                "strict": True,
            },
        }
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            content = await self.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except Exception:
            # Fallback: plain JSON without response_format (works for providers
            # that don't implement the JSON-Schema format).
            messages[0] = {
                "role": "system",
                "content": (
                    f"{system}\n\nReturn ONLY valid JSON matching this schema:\n"
                    f"{json.dumps(json_schema)}"
                ),
            }
            content = await self.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)

        data = _loads_lenient(content)
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            log.warning("llm.structured.validation_failed", errors=exc.errors(), raw=content[:500])
            raise LLMError(f"structured output did not validate: {exc}") from exc


def _loads_lenient(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("```"):
        # strip markdown fences
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines)
    return json.loads(raw)


def _strip_for_openai(schema: dict[str, Any]) -> dict[str, Any]:
    """Some providers reject Pydantic's extra fields in response_format schemas."""
    dropped = {"title", "$defs"}
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k in dropped:
            continue
        if isinstance(v, dict):
            out[k] = _strip_for_openai(v)
        elif isinstance(v, list):
            out[k] = [_strip_for_openai(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    # OpenAI strict mode wants additionalProperties: false and required set.
    if out.get("type") == "object" and "additionalProperties" not in out:
        out["additionalProperties"] = False
    return out


_default_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
