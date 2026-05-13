"""data_export job table for workspace + user portability dumps.

Revision ID: 20260513_0005
Revises: 20260513_0004
Create Date: 2026-05-13

Phase G2 of the production-readiness pass. One row per export request.
Status transitions:

    queued → running → completed | failed

When ``status='completed'``, ``object_key`` points at the gzipped JSONL
in MinIO/S3 and ``download_expires_at`` carries the pre-signed URL's
expiry. The URL itself isn't stored — callers re-presign on read.

Two scopes:
* ``scope='workspace'`` — full workspace dump; requires workspace_id.
* ``scope='user'`` — GDPR right-to-portability dump for one user;
  workspace_id is NULL, requester_user_id is the subject.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0005"
down_revision: str | None = "20260513_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE export_job (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid REFERENCES workspace(id) ON DELETE CASCADE,
          requester_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
          scope text NOT NULL CHECK (scope IN ('workspace','user')),
          status text NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued','running','completed','failed')),
          object_key text,
          byte_size bigint,
          download_expires_at timestamptz,
          error_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CHECK (
            (scope = 'workspace' AND workspace_id IS NOT NULL)
            OR (scope = 'user' AND workspace_id IS NULL)
          )
        );
        CREATE INDEX export_job_workspace_idx
          ON export_job(workspace_id, created_at DESC)
          WHERE workspace_id IS NOT NULL;
        CREATE INDEX export_job_user_idx
          ON export_job(requester_user_id, created_at DESC)
          WHERE scope = 'user';
        """
    )

    # RLS only for workspace-scoped rows. User-scoped rows (scope='user')
    # are filtered in app code by requester_user_id.
    op.execute("ALTER TABLE export_job ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY export_job_ws_select ON export_job FOR SELECT
          USING (
            scope = 'user'
            OR current_workspace_id() IS NULL
            OR workspace_id = current_workspace_id()
          );
        CREATE POLICY export_job_ws_modify ON export_job FOR ALL
          USING (
            scope = 'user'
            OR current_workspace_id() IS NULL
            OR workspace_id = current_workspace_id()
          )
          WITH CHECK (
            scope = 'user'
            OR current_workspace_id() IS NULL
            OR workspace_id = current_workspace_id()
          );
        """
    )
    op.execute("ALTER TABLE export_job FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS export_job CASCADE")
