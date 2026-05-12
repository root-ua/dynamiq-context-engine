"""agent_token table for long-lived MCP bearer tokens

Revision ID: 20260422_0001
Revises: 20260421_0003
Create Date: 2026-04-22

External agents (Claude Code, Cursor, Claude Desktop) connect with a static
bearer token. The 60-minute JWT we mint for the browser session is too
short for a client config, and rotating it would log the user out of the
web UI. These tokens are separate: per-workspace, argon2-hashed at rest,
revocable, and verified on every MCP request.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260422_0001"
down_revision: str | None = "20260421_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_token (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          name text NOT NULL,
          prefix text NOT NULL,
          token_hash text NOT NULL,
          scopes text[] NOT NULL DEFAULT ARRAY['mcp']::text[],
          last_used_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz,
          revoked_at timestamptz
        );
        CREATE INDEX IF NOT EXISTS agent_token_workspace_idx
          ON agent_token(workspace_id);
        CREATE INDEX IF NOT EXISTS agent_token_prefix_idx
          ON agent_token(prefix);
        """
    )

    # RLS: by default rows are only visible to matching workspace.
    op.execute(
        """
        ALTER TABLE agent_token ENABLE ROW LEVEL SECURITY;
        ALTER TABLE agent_token FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS agent_token_ws_policy ON agent_token;
        CREATE POLICY agent_token_ws_policy ON agent_token
          USING (
            workspace_id = current_workspace_id()
            OR current_workspace_id() IS NULL
          )
          WITH CHECK (
            workspace_id = current_workspace_id()
            OR current_workspace_id() IS NULL
          );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_token CASCADE")
