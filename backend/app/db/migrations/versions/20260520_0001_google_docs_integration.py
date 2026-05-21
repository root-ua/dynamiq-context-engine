"""Google Docs integration: connections, identities, sync state, ACL projection.

Revision ID: 20260520_0001
Revises: 20260514_0001
Create Date: 2026-05-20

Adds the schema for the v1 Google Docs integration (see plan
``.claude/plans/so-i-want-to-zippy-puppy.md``):

* ``user_external_identity``   — workspace user ↔ verified Google email.
                                  Rebuilds the table dropped by 20260514_0001
                                  but only with the columns v1+v2 actually use.
* ``google_drive_connection``  — per-user OAuth tokens (encrypted at rest)
                                  + selection JSON.
* ``google_doc_sync_state``    — per-doc ledger for dedup + status tracking.
* ``episode_external_acl``     — per-episode projection of the source doc's
                                  Drive permissions. Captured in v1; the
                                  retrieval-layer enforcement is v2.
* ``google_docs_sync_job``     — one row per "Sync now" click for the UI
                                  progress tracker.

RLS pattern: ENABLE + FORCE + ws_select/ws_modify policy matching every
other workspace-scoped table.

Downgrade drops all five tables. There is no archival of OAuth tokens —
clients must reconnect.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260520_0001"
down_revision: str | None = "20260514_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = [
    "user_external_identity",
    "google_drive_connection",
    "google_doc_sync_state",
    "episode_external_acl",
    "google_docs_sync_job",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_external_identity (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          provider text NOT NULL CHECK (provider IN ('google')),
          email citext NOT NULL,
          domain citext NOT NULL,
          verified_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (workspace_id, user_id, provider, email)
        );
        CREATE INDEX uxi_workspace_user_idx
          ON user_external_identity (workspace_id, user_id);
        CREATE INDEX uxi_workspace_email_idx
          ON user_external_identity (workspace_id, email);
        """
    )

    op.execute(
        """
        CREATE TABLE google_drive_connection (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          account_email citext NOT NULL,
          oauth_access_token bytea NOT NULL,
          oauth_refresh_token bytea NOT NULL,
          oauth_expires_at timestamptz NOT NULL,
          scopes text[] NOT NULL DEFAULT '{}',
          selection jsonb NOT NULL DEFAULT '{"folders":[],"files":[]}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          revoked_at timestamptz,
          UNIQUE (workspace_id, user_id, account_email)
        );
        CREATE INDEX gdc_workspace_idx ON google_drive_connection(workspace_id);
        """
    )

    op.execute(
        """
        CREATE TABLE google_doc_sync_state (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          connection_id uuid NOT NULL REFERENCES google_drive_connection(id) ON DELETE CASCADE,
          google_doc_id text NOT NULL,
          doc_title text,
          doc_modified_at timestamptz,
          content_hash text,
          episode_id uuid REFERENCES episode(id) ON DELETE SET NULL,
          status text NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','syncing','completed','failed','skipped')),
          error text,
          last_synced_at timestamptz,
          UNIQUE (connection_id, google_doc_id)
        );
        CREATE INDEX gdss_connection_idx ON google_doc_sync_state(connection_id);
        CREATE INDEX gdss_workspace_status_idx
          ON google_doc_sync_state(workspace_id, status);
        """
    )

    op.execute(
        """
        CREATE TABLE episode_external_acl (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          episode_id uuid NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
          ace_kind text NOT NULL
            CHECK (ace_kind IN ('anyone','domain','user','group')),
          email citext,
          domain citext,
          role text NOT NULL,
          provider text NOT NULL DEFAULT 'google_drive',
          source_doc_id text NOT NULL,
          synced_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX eea_episode_idx ON episode_external_acl(episode_id);
        CREATE INDEX eea_ws_email_idx ON episode_external_acl(workspace_id, email)
          WHERE email IS NOT NULL;
        CREATE INDEX eea_ws_domain_idx ON episode_external_acl(workspace_id, domain)
          WHERE domain IS NOT NULL;
        CREATE INDEX eea_ws_anyone_idx ON episode_external_acl(workspace_id)
          WHERE ace_kind = 'anyone';
        """
    )

    op.execute(
        """
        CREATE TABLE google_docs_sync_job (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          connection_id uuid NOT NULL REFERENCES google_drive_connection(id) ON DELETE CASCADE,
          triggered_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
          status text NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued','running','completed','failed','cancelled')),
          total_docs integer NOT NULL DEFAULT 0,
          processed_docs integer NOT NULL DEFAULT 0,
          failed_docs integer NOT NULL DEFAULT 0,
          skipped_docs integer NOT NULL DEFAULT 0,
          error text,
          created_at timestamptz NOT NULL DEFAULT now(),
          started_at timestamptz,
          completed_at timestamptz
        );
        CREATE INDEX gdsj_workspace_status_idx
          ON google_docs_sync_job(workspace_id, status);
        CREATE INDEX gdsj_connection_idx
          ON google_docs_sync_job(connection_id);
        """
    )

    # RLS: same ENABLE + FORCE + ws_select / ws_modify pattern as every
    # other workspace-scoped table in this schema.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_ws_select
              ON {table} FOR SELECT
              USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
            CREATE POLICY {table}_ws_modify
              ON {table} FOR ALL
              USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id())
              WITH CHECK (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
            """
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Drop in reverse FK order. CASCADE cleans up the policies.
    op.execute("DROP TABLE IF EXISTS google_docs_sync_job CASCADE")
    op.execute("DROP TABLE IF EXISTS episode_external_acl CASCADE")
    op.execute("DROP TABLE IF EXISTS google_doc_sync_state CASCADE")
    op.execute("DROP TABLE IF EXISTS google_drive_connection CASCADE")
    op.execute("DROP TABLE IF EXISTS user_external_identity CASCADE")
