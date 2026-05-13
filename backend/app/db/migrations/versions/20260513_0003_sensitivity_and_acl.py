"""Sensitivity labels + generalized per-fact ACL + high-sensitivity flag.

Revision ID: 20260513_0003
Revises: 20260513_0002
Create Date: 2026-05-13

Phase B of RFC-001 v3 alignment.

Schema:

* ``sensitivity_label`` — typed labels with an ``ltree`` hierarchy
  (mirrors entity_type), letting policies match all descendants of a
  parent label.
* ``episode_label`` / ``edge_label`` — many-to-many assignment tables.
  Workspace_id is denormalized for RLS-on-FORCE plus easy index scans.
* ``label_policy`` — declarative rule rows; the domain layer evaluates
  them in Python (cheap; rule count is tiny relative to fact count).
* ``edge.allowed_principals`` / ``episode.allowed_principals`` — opt-in
  denormalized per-fact ACL array. The existing per-source ACL stays the
  source of truth for connector-ingested facts; this column carries the
  agentic / manual edits where source-derived ACL isn't applicable.
* ``workspace.high_sensitivity`` — boolean flag turning on the
  source-recheck path during retrieval.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0003"
down_revision: str | None = "20260513_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sensitivity_label (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          slug text NOT NULL,
          name text NOT NULL,
          description text,
          color text,
          path ltree NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (workspace_id, slug)
        );
        CREATE INDEX sensitivity_label_path_gist
          ON sensitivity_label USING gist (path);
        CREATE TRIGGER sensitivity_label_updated_at
          BEFORE UPDATE ON sensitivity_label
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TABLE episode_label (
          episode_id uuid NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
          label_id uuid NOT NULL REFERENCES sensitivity_label(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          assigned_at timestamptz NOT NULL DEFAULT now(),
          assigned_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
          PRIMARY KEY (episode_id, label_id)
        );
        CREATE INDEX episode_label_label_idx ON episode_label(label_id);

        CREATE TABLE edge_label (
          edge_id uuid NOT NULL REFERENCES edge(id) ON DELETE CASCADE,
          label_id uuid NOT NULL REFERENCES sensitivity_label(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          assigned_at timestamptz NOT NULL DEFAULT now(),
          assigned_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
          PRIMARY KEY (edge_id, label_id)
        );
        CREATE INDEX edge_label_label_idx ON edge_label(label_id);
        """
    )

    op.execute(
        """
        CREATE TABLE label_policy (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          name text NOT NULL,
          rule jsonb NOT NULL,
          action text NOT NULL CHECK (action IN ('drop','warn','block')),
          enabled boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX label_policy_workspace_idx
          ON label_policy(workspace_id) WHERE enabled;
        CREATE TRIGGER label_policy_updated_at
          BEFORE UPDATE ON label_policy
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        ALTER TABLE edge    ADD COLUMN allowed_principals text[];
        ALTER TABLE episode ADD COLUMN allowed_principals text[];
        CREATE INDEX edge_allowed_principals_idx
          ON edge USING gin (allowed_principals)
          WHERE allowed_principals IS NOT NULL;
        CREATE INDEX episode_allowed_principals_idx
          ON episode USING gin (allowed_principals)
          WHERE allowed_principals IS NOT NULL;

        ALTER TABLE workspace
          ADD COLUMN high_sensitivity boolean NOT NULL DEFAULT false;
        """
    )

    for table in ("sensitivity_label", "episode_label", "edge_label", "label_policy"):
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
    op.execute(
        """
        ALTER TABLE workspace DROP COLUMN IF EXISTS high_sensitivity;
        ALTER TABLE episode   DROP COLUMN IF EXISTS allowed_principals;
        ALTER TABLE edge      DROP COLUMN IF EXISTS allowed_principals;
        """
    )
    op.execute("DROP TABLE IF EXISTS label_policy CASCADE")
    op.execute("DROP TABLE IF EXISTS edge_label CASCADE")
    op.execute("DROP TABLE IF EXISTS episode_label CASCADE")
    op.execute("DROP TABLE IF EXISTS sensitivity_label CASCADE")
