import logging
import re
import sys

import structlog

_REDACT_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "secret",
        "client_secret",
        "credentials",
        "credentials_encrypted",
    }
)

# Catch raw bearer tokens / API keys in free-text values.
_BEARER_RE = re.compile(r"(?i)bearer\s+[a-z0-9._\-]+")
# OpenAI-style sk-xxxx (and similar) — at least 20 chars after the prefix.
_OPENAI_RE = re.compile(r"sk-[A-Za-z0-9_\-]{20,}")
# Long random-looking tokens we can't classify by key name.
_GENERIC_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        value = _BEARER_RE.sub("[redacted-bearer]", value)
        value = _OPENAI_RE.sub("[redacted-api-key]", value)
        value = _GENERIC_TOKEN_RE.sub("[redacted-token]", value)
        return value
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def redact_pii(_logger: object, _name: str, event_dict: dict) -> dict:
    """structlog processor: redact sensitive keys + value patterns.

    Keys in ``_REDACT_KEYS`` always get masked. Values across the dict
    are scanned for bearer tokens, API keys, and 40+ char random strings.
    Adds minimal CPU at our log volume.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "[redacted]"
            continue
        event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_pii,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
