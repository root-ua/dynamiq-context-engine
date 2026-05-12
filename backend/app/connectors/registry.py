"""Connector registry — kind string → connector class.

Connectors register themselves at import time. To add one, import its
module here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.connectors.base import CrawlerConnector


_REGISTRY: dict[str, type["CrawlerConnector"]] = {}


def register(connector_cls: type["CrawlerConnector"]) -> type["CrawlerConnector"]:
    """Decorator: register a connector class by its ``.kind`` attribute."""
    if not getattr(connector_cls, "kind", None):
        raise TypeError(
            f"{connector_cls.__name__} must define a non-empty `kind` class attr"
        )
    if connector_cls.kind in _REGISTRY:
        existing = _REGISTRY[connector_cls.kind].__name__
        if existing != connector_cls.__name__:
            raise RuntimeError(
                f"connector kind {connector_cls.kind!r} already registered "
                f"to {existing}; cannot re-register to {connector_cls.__name__}"
            )
    _REGISTRY[connector_cls.kind] = connector_cls
    return connector_cls


def get(kind: str) -> type["CrawlerConnector"]:
    if kind not in _REGISTRY:
        raise KeyError(f"unknown connector kind: {kind!r}")
    return _REGISTRY[kind]


def list_kinds() -> list[str]:
    return sorted(_REGISTRY.keys())


def _import_connectors() -> None:
    """Import all connector modules so their @register decorators run.

    Called once by the API/worker entry points to populate the registry
    without forcing import-on-load (which would create circular imports
    with the framework's own helpers).
    """
    # Side-effect imports; ignore unused-import warnings.
    from app.connectors import google_drive  # noqa: F401
