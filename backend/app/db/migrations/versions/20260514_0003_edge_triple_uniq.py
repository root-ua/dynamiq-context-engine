"""Partial unique index for exact-triple edge dedup.

Revision ID: 20260514_0003
Revises: 20260514_0002
Create Date: 2026-05-14

Phase PP2. App-layer dedup in ``add_fact`` is the primary guard, but
this index is a defense-in-depth safety net: a future code path (or
a race that slipped through) cannot create two LIVE edges for the
same (workspace_id, subject_id, predicate_id, object_id, lower(valid_time)).

The index keys ``lower(valid_time)`` so multiple time-shifted edges
of the same triple stay legal — a refinement to a fact's range isn't
a duplicate. The condition limits to currently-live system rows.

Pre-flight cleanup: collapse any pre-existing duplicates (smallest id
wins; the rest get ``sys_time`` closed) so the index can be created
without rejecting existing data.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260514_0003"
down_revision: str | None = "20260514_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-flight: close all but the earliest-inserted live duplicate per
    # (workspace, subject, predicate, object, lower(valid_time)) tuple.
    op.execute(
        """
        WITH dups AS (
          SELECT id,
                 ROW_NUMBER() OVER (
                   PARTITION BY workspace_id, subject_id, predicate_id,
                                object_id, lower(valid_time)
                   ORDER BY lower(sys_time), id
                 ) AS rn
          FROM edge
          WHERE upper(sys_time) = 'infinity'
        )
        UPDATE edge
        SET sys_time = tstzrange(lower(sys_time), clock_timestamp(), '[)')
        WHERE id IN (SELECT id FROM dups WHERE rn > 1)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS edge_live_triple_uniq
          ON edge (workspace_id, subject_id, predicate_id, object_id, lower(valid_time))
          WHERE upper(sys_time) = 'infinity'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS edge_live_triple_uniq")
