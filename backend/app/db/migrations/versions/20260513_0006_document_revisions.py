"""document revisions — block-tree snapshots for restore.

Revision ID: 20260513_0006
Revises: 20260513_0005
Create Date: 2026-05-13

A user can save an explicit revision at any time (UI button) and the
Hocuspocus persistence hook can also drop a snapshot on a debounce. The
``blocks_snapshot`` jsonb is the frozen-in-time block tree exactly as it
would be returned from ``GET /api/documents/:id/blocks``; restore is a
direct PUT into block.

``yjs_state`` is optional and currently unused — reserved for a future
"restore at edit granularity" feature without re-engineering the table.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0006"
down_revision: str | None = "20260513_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_revision (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          document_id uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
          blocks_snapshot jsonb NOT NULL,
          yjs_state bytea,
          created_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          note text
        );
        CREATE INDEX document_revision_doc_idx
          ON document_revision(document_id, created_at DESC);
        CREATE INDEX document_revision_workspace_idx
          ON document_revision(workspace_id, created_at DESC);
        """
    )

    op.execute("ALTER TABLE document_revision ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_revision_ws_select ON document_revision FOR SELECT
          USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
        CREATE POLICY document_revision_ws_modify ON document_revision FOR ALL
          USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id())
          WITH CHECK (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
        """
    )
    op.execute("ALTER TABLE document_revision FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_revision CASCADE")
