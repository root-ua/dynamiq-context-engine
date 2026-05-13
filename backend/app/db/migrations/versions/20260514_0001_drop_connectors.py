"""Drop the connector framework tables and episode columns.

Revision ID: 20260514_0001
Revises: 20260513_0007
Create Date: 2026-05-14

Architectural pivot (Phase R): ingestion is the agent's responsibility,
not the platform's. The platform no longer pulls from Drive/Notion/etc.
itself — calling agents (Claude Code, ChatGPT, custom agents) decide
what to push in via the MCP ``add_episode`` and ``add_fact`` tools.

This migration removes everything that existed only to support the
in-platform connector framework:

* ``episode_acl`` — per-source ACL projection. No source, no per-source
  ACL. Workspace RLS + sensitivity labels are the entire ACL surface.
* ``user_external_identity`` — bridged Dynamiq users to source-system
  principals. Unused without connectors.
* ``connector_instance`` — OAuth credentials + crawl cursors. Unused.
* ``episode.connector_instance_id`` / ``external_id`` / ``external_url``
  / ``external_revision_id`` / ``content_hash`` / ``mime_type`` /
  ``acl`` / ``acl_synced_at`` / ``last_modified_external`` — episode
  fields that only mattered for connector-pulled content.

The ``workspace.high_sensitivity`` flag is kept (deprecated) — agents
may still use it as a hint that a workspace requires stricter
prompting.

The downgrade is intentionally non-functional: there is no clean way to
restore the dropped columns without the original data, and trying to
half-restore would silently lose state. Anyone needing to roll back
must restore from backup.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260514_0001"
down_revision: str | None = "20260513_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop connector-coupled tables. CASCADE handles any leftover FK
    # references (the columns we drop below may carry FKs into them).
    op.execute("DROP TABLE IF EXISTS episode_acl CASCADE")
    op.execute("DROP TABLE IF EXISTS user_external_identity CASCADE")
    op.execute("DROP TABLE IF EXISTS connector_instance CASCADE")

    # Drop episode columns that only existed for connector-sourced rows.
    op.execute(
        """
        ALTER TABLE episode
          DROP COLUMN IF EXISTS connector_instance_id,
          DROP COLUMN IF EXISTS external_id,
          DROP COLUMN IF EXISTS external_url,
          DROP COLUMN IF EXISTS external_revision_id,
          DROP COLUMN IF EXISTS content_hash,
          DROP COLUMN IF EXISTS mime_type,
          DROP COLUMN IF EXISTS acl,
          DROP COLUMN IF EXISTS acl_synced_at,
          DROP COLUMN IF EXISTS last_modified_external
        """
    )

    # Drop the parallel ``allowed_principals[]`` denormalised fast-path
    # column from the bi-temporal edge and episode tables. It was only
    # used by the per-source ACL filter, which is gone.
    op.execute(
        "ALTER TABLE edge DROP COLUMN IF EXISTS allowed_principals"
    )
    op.execute(
        "ALTER TABLE episode DROP COLUMN IF EXISTS allowed_principals"
    )


def downgrade() -> None:
    raise RuntimeError(
        "connector removal is one-way; restore from backup if you need"
        " the connector framework back"
    )
