"""Entity resolution cascade — external refs + LLM verdict cache

Revision ID: 20260513_0002
Revises: 20260513_0001
Create Date: 2026-05-13

Phase C of RFC-001 v3 alignment. Two tables:

* ``entity_external_ref`` — stable identifiers (email, slug, connector
  file-id, Message-ID) that let Tier-1 exact-match resolution avoid the
  trigram path entirely. Composite primary key
  ``(workspace_id, kind, value)`` so the same external id in two
  workspaces points at two different entities.

* ``entity_resolution_decision`` — cache of LLM verdicts on ambiguous
  pairs so we never pay for the same judgment twice. The canonical
  ordering (``a_id < b_id``) collapses each unordered pair onto one row.

Both tables are workspace-scoped with the standard RLS pattern.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0002"
down_revision: str | None = "20260513_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_external_ref (
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          entity_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          kind text NOT NULL,
          value citext NOT NULL,
          source_ref text,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (workspace_id, kind, value)
        );
        CREATE INDEX entity_external_ref_entity_idx
          ON entity_external_ref(entity_id);
        CREATE INDEX entity_external_ref_workspace_kind_idx
          ON entity_external_ref(workspace_id, kind);
        """
    )

    op.execute(
        """
        CREATE TABLE entity_resolution_decision (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          a_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          b_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          decision text NOT NULL
            CHECK (decision IN ('match','no_match','uncertain')),
          confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
          rationale text,
          agent_ref text,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (workspace_id, a_id, b_id),
          CHECK (a_id < b_id)
        );
        CREATE INDEX entity_resolution_decision_workspace_idx
          ON entity_resolution_decision(workspace_id);
        """
    )

    for table in ("entity_external_ref", "entity_resolution_decision"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_ws_select ON {table} FOR SELECT
              USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
            CREATE POLICY {table}_ws_modify ON {table} FOR ALL
              USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id())
              WITH CHECK (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
            """
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_resolution_decision CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_external_ref CASCADE")
