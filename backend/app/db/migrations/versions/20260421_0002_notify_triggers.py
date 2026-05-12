"""notify triggers for reactive UI

Revision ID: 20260421_0002
Revises: 20260421_0001
Create Date: 2026-04-21
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260421_0002"
down_revision: str | None = "20260421_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_workspace_event() RETURNS TRIGGER AS $$
        DECLARE
          ws_id uuid;
          payload jsonb;
          op_name text;
        BEGIN
          ws_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
          op_name := LOWER(TG_OP);
          payload := jsonb_build_object(
            'op', op_name,
            'table', TG_TABLE_NAME,
            'id', COALESCE(NEW.id::text, OLD.id::text),
            'workspace_id', ws_id::text,
            'at', now()
          );
          PERFORM pg_notify('workspace:' || ws_id::text, payload::text);
          RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in ("entity", "edge", "document", "block", "episode",
                  "entity_type", "relation_type", "audit_log"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_notify
              AFTER INSERT OR UPDATE OR DELETE ON {table}
              FOR EACH ROW EXECUTE FUNCTION notify_workspace_event();
            """
        )


def downgrade() -> None:
    for table in ("entity", "edge", "document", "block", "episode",
                  "entity_type", "relation_type", "audit_log"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_notify ON {table}")
    op.execute("DROP FUNCTION IF EXISTS notify_workspace_event()")
