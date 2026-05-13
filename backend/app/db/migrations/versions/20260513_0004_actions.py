"""Kinetic actions — typed write-back operations with provenance + idempotency.

Revision ID: 20260513_0004
Revises: 20260513_0003
Create Date: 2026-05-13

Phase D of RFC-001 v3 alignment.

Two tables:

* ``action_type`` — registered action definitions. ``input_schema`` is
  JSON-Schema validated client-side and re-validated on invocation.
  ``side_effects`` declares what the action does so the UI can render a
  preview before invocation. ``required_role`` gates by workspace role.
* ``action_invocation`` — one row per invocation, with idempotency key,
  status, and a back-reference to ``prov_activity`` (the same row the
  caller created at the start of the action).

The (workspace, action_type, idempotency_key) uniqueness gives us free
de-duplication; a re-invocation with the same key returns the cached
result without re-running side effects.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0004"
down_revision: str | None = "20260513_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE action_type (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          slug text NOT NULL,
          name text NOT NULL,
          description text,
          source_kind text,
          input_schema jsonb NOT NULL,
          required_role text NOT NULL DEFAULT 'editor'
            CHECK (required_role IN ('viewer','editor','admin','owner')),
          idempotency_required boolean NOT NULL DEFAULT true,
          requires_approval boolean NOT NULL DEFAULT false,
          side_effects jsonb NOT NULL DEFAULT '[]'::jsonb,
          enabled boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (workspace_id, slug)
        );
        CREATE TRIGGER action_type_updated_at BEFORE UPDATE ON action_type
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TABLE action_invocation (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          action_type_id uuid NOT NULL REFERENCES action_type(id) ON DELETE CASCADE,
          principal_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
          principal_agent_token_id uuid REFERENCES agent_token(id) ON DELETE SET NULL,
          idempotency_key text NOT NULL,
          input jsonb NOT NULL,
          status text NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','approved','executing','completed','failed','rejected')),
          result jsonb,
          error_message text,
          prov_activity_id uuid REFERENCES prov_activity(id) ON DELETE SET NULL,
          emitted_edge_id uuid REFERENCES edge(id) ON DELETE SET NULL,
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          UNIQUE (workspace_id, action_type_id, idempotency_key)
        );
        CREATE INDEX action_invocation_workspace_status_idx
          ON action_invocation(workspace_id, status, started_at DESC);
        CREATE INDEX action_invocation_action_type_idx
          ON action_invocation(action_type_id, started_at DESC);
        """
    )

    for table in ("action_type", "action_invocation"):
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
    op.execute("DROP TABLE IF EXISTS action_invocation CASCADE")
    op.execute("DROP TABLE IF EXISTS action_type CASCADE")
