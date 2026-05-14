"""Episode content-hash dedup.

Revision ID: 20260514_0002
Revises: 20260514_0001
Create Date: 2026-05-14

Phase PP3. Same ``content_text`` submitted twice currently lands two
``episode`` rows + two extraction runs + fan-out of duplicate edges.
Hash the content (sha256) and unique it per workspace so retries +
identical re-postings dedupe at the DB.

Backfill is straightforward — every existing row gets a fresh hash.
The partial index excludes soft-deleted rows so deletion + re-ingest
of the same content is a legitimate re-create.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260514_0002"
down_revision: str | None = "20260514_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto already enabled in the initial migration; digest() is
    # available.
    op.execute(
        """
        ALTER TABLE episode
          ADD COLUMN IF NOT EXISTS content_hash bytea
        """
    )

    # Backfill — sha256 of content_text (or empty string when null).
    op.execute(
        """
        UPDATE episode
        SET content_hash = digest(coalesce(content_text, ''), 'sha256')
        WHERE content_hash IS NULL
        """
    )

    op.execute(
        """
        ALTER TABLE episode
          ALTER COLUMN content_hash SET NOT NULL
        """
    )

    # Partial unique index — only constrains live (non-soft-deleted)
    # rows. Workspace-scoped. Two different workspaces can hold the
    # same content; the same workspace can't.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS episode_content_hash_uniq
          ON episode (workspace_id, content_hash)
          WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS episode_content_hash_uniq")
    op.execute("ALTER TABLE episode DROP COLUMN IF EXISTS content_hash")
