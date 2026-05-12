"""pgvector helpers: format Python lists as literals for asyncpg/sqlalchemy text()."""
from __future__ import annotations

from collections.abc import Sequence


def to_pg_vector(values: Sequence[float] | None) -> str | None:
    if values is None:
        return None
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"
