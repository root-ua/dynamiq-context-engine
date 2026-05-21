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
        # Intentionally NOT setting litellm.api_key — that's a global
        # fallback that leaks across providers (e.g. an Anthropic key
        # would be sent to OpenAI's endpoint and 401). LiteLLM already
        # resolves per-provider keys from env vars (ANTHROPIC_API_KEY,
        # OPENAI_API_KEY, etc.) which are populated by our settings
        # layer. Keep it that way.

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
        # Reasoning models (OpenAI gpt-5 / o-series, Anthropic claude-sonnet
        # extended thinking) only accept temperature=1 and use
        # max_completion_tokens instead of max_tokens. Detect by model
        # family and route the parameters accordingly so callers can keep
        # their "set temperature=0.1 for determinism" intent without
        # crashing the API.
        is_reasoning = _is_reasoning_model(self.model_id)
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "response_format": response_format,
        }
        if is_reasoning:
            # Drop temperature entirely (default behavior). Reasoning
            # models are deterministic-ish by construction; the temperature
            # knob is not exposed.
            if max_tokens is not None:
                kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

        response = await litellm.acompletion(**kwargs)
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
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # The most common cause is the LLM hitting its max_tokens cap mid-output,
        # which produces an unterminated string. Surface that diagnosis instead
        # of just propagating the cryptic "Unterminated string ..." message.
        hint = ""
        if "Unterminated string" in str(exc) or "Expecting" in str(exc):
            hint = (
                " (likely max_tokens too low — the LLM was cut off mid-output; "
                "raise max_tokens on the structured() call or split the input)."
            )
        log.warning(
            "llm.structured.json_decode_failed",
            error=str(exc),
            raw_tail=raw[-200:],
            raw_len=len(raw),
        )
        raise LLMError(f"LLM did not return valid JSON: {exc}{hint}") from exc


def _strip_for_openai(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Pydantic schema for provider response_format slots.

    Anthropic's strict json_schema mode rejects `$ref` — it wants the full
    object inlined. OpenAI strict mode wants `additionalProperties: false`
    and `title` removed. So we inline `$defs` first, then walk the tree
    dropping `title`/`$defs` and adding `additionalProperties: false`.
    """
    inlined = _inline_defs(schema)
    return _strip_walk(inlined)


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs", {}) or {}

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.split("/", 2)[-1]
                target = defs.get(name)
                if target is None:
                    return {k: resolve(v) for k, v in node.items() if k != "$ref"}
                # Inline a deep-resolved copy; preserve sibling keys from the
                # ref site (rare, but JSON Schema allows it).
                inlined = resolve(target)
                sibling = {k: resolve(v) for k, v in node.items() if k != "$ref"}
                if isinstance(inlined, dict):
                    return {**inlined, **sibling}
                return inlined
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _strip_walk(schema: dict[str, Any]) -> dict[str, Any]:
    dropped = {"title", "$defs"}
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k in dropped:
            continue
        if isinstance(v, dict):
            out[k] = _strip_walk(v)
        elif isinstance(v, list):
            out[k] = [_strip_walk(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    if out.get("type") == "object" and "additionalProperties" not in out:
        out["additionalProperties"] = False
    return out


def _is_reasoning_model(model_id: str) -> bool:
    """Detect OpenAI reasoning models (gpt-5*, o1*, o3*, o4*).

    These have stricter parameter requirements: temperature must be 1
    (default) and the output cap is `max_completion_tokens`, not
    `max_tokens`. The provider/ prefix in model_id is optional.
    """
    name = model_id.split("/", 1)[-1].lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


_default_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
