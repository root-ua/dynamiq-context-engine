"""workspace_invite table for link-based team invites

Revision ID: 20260423_0001
Revises: 20260422_0001
Create Date: 2026-04-23

Link-based (not email-based) workspace invites. The owner generates an
invite, copies the `/invite/<token>` URL, and shares it out-of-band.
Any authenticated user visiting that URL with a valid unexpired unused
token gets added to workspace_member at the specified role.

No email sending here — that's intentional for v1. Email-based invites
(drop-in: invited_email is already stored) can layer on later once we
have SMTP/Resend wired for transactional email beyond auth.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260423_0001"
down_revision: str | None = "20260422_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_invite (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL
            REFERENCES workspace(id) ON DELETE CASCADE,
          invited_email citext,
          invited_by uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          role text NOT NULL CHECK (role IN ('owner','admin','editor','viewer')),
          token text NOT NULL UNIQUE,
          expires_at timestamptz NOT NULL,
          accepted_at timestamptz,
          accepted_by uuid REFERENCES app_user(id),
          revoked_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS workspace_invite_ws_idx
          ON workspace_invite(workspace_id);
        CREATE INDEX IF NOT EXISTS workspace_invite_token_idx
          ON workspace_invite(token);
        """
    )

    op.execute(
        """
        ALTER TABLE workspace_invite ENABLE ROW LEVEL SECURITY;
        ALTER TABLE workspace_invite FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS workspace_invite_ws_policy ON workspace_invite;
        CREATE POLICY workspace_invite_ws_policy ON workspace_invite
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
    op.execute("DROP TABLE IF EXISTS workspace_invite CASCADE")
