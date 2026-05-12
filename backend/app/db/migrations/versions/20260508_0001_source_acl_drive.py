"""source-aware ACLs + Google Drive connector substrate

Revision ID: 20260508_0001
Revises: 20260423_0001
Create Date: 2026-05-08

Adds the foundation for facts to inherit access from the source documents
they were extracted from, so a user querying via MCP only sees facts
backed by sources they personally can access in the source system.

Three new concepts:

* ``connector_instance`` — a configured external source (e.g. one Google
  Drive workspace), with encrypted OAuth credentials and a resume cursor
  for incremental crawls.
* ``user_external_identity`` — a per-workspace mapping from internal
  ``app_user.id`` to an external principal (Google ``sub``, email, group
  memberships). The bridge that lets us answer "is this caller the same
  person as the one in this Drive ACL?".
* ``episode_acl`` — a normalized projection of the source-system ACL
  snapshotted at crawl time. Indexed for the visibility filter; the
  canonical snapshot lives in ``episode.acl`` (jsonb).

``episode`` is extended with connector-specific columns. Episodes remain
the bi-temporal ground truth; we don't fork them into a parallel
``source_document`` table.

``agent_token`` gets a ``kind`` discriminator (``user`` vs ``service``).
The Principal that the auth layer constructs uses this to decide whether
to apply the per-source ACL filter (user) or bypass it (service —
crawler workers must be able to write all source content regardless of
who can read it). All existing tokens were workspace-scoped service
tokens by definition, so the column defaults to ``'service'`` and
preserves current semantics.

No trigger enforcing "connector-derived edges must have source_id" — the
visibility query handles missing source as "user/agent-asserted within
workspace" via the existing role check. Application code in the
extraction pipeline is responsible for threading source_id through.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260508_0001"
down_revision: str | None = "20260423_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # connector_instance — one configured connector per workspace per source.
    # Credentials are pgcrypto-encrypted at rest; the key id lets us
    # rotate the symmetric key without re-encrypting everything atomically.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE connector_instance (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          connector_kind text NOT NULL,
          display_name text NOT NULL,
          config jsonb NOT NULL DEFAULT '{}'::jsonb,
          credentials_encrypted bytea,
          credentials_key_id text,
          status text NOT NULL DEFAULT 'inactive'
            CHECK (status IN ('inactive','authorizing','active','paused','error')),
          last_full_crawl_at timestamptz,
          last_incremental_at timestamptz,
          cursor jsonb,
          last_error text,
          created_by uuid NOT NULL REFERENCES app_user(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz
        );
        CREATE INDEX connector_instance_workspace_idx
          ON connector_instance(workspace_id) WHERE deleted_at IS NULL;
        CREATE INDEX connector_instance_kind_idx
          ON connector_instance(connector_kind) WHERE deleted_at IS NULL;
        CREATE TRIGGER connector_instance_updated_at BEFORE UPDATE ON connector_instance
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ------------------------------------------------------------------
    # user_external_identity — identity bridge.
    #
    # Per-workspace because identity is granted per-workspace (a user's
    # Google account being linked in workspace A doesn't authorize them
    # in workspace B even if they're a member of both).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE user_external_identity (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          provider text NOT NULL,
          external_id text NOT NULL,
          external_email text,
          groups jsonb NOT NULL DEFAULT '[]'::jsonb,
          groups_synced_at timestamptz,
          groups_resolution text NOT NULL DEFAULT 'self'
            CHECK (groups_resolution IN ('self','admin_sdk','none')),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (workspace_id, provider, external_id)
        );
        CREATE INDEX user_external_identity_user_idx
          ON user_external_identity(user_id, workspace_id);
        CREATE INDEX user_external_identity_email_idx
          ON user_external_identity(workspace_id, provider, lower(external_email))
          WHERE external_email IS NOT NULL;
        CREATE TRIGGER user_external_identity_updated_at BEFORE UPDATE ON user_external_identity
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ------------------------------------------------------------------
    # episode — extend with connector-source fields + ACL snapshot.
    #
    # Existing rows have all new columns NULL: they're user/agent-asserted
    # episodes, not connector-ingested. The visibility filter treats those
    # as "visible to any workspace member" (existing semantics).
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE episode
          ADD COLUMN connector_instance_id uuid
            REFERENCES connector_instance(id) ON DELETE RESTRICT,
          ADD COLUMN external_id text,
          ADD COLUMN external_url text,
          ADD COLUMN external_revision_id text,
          ADD COLUMN content_hash text,
          ADD COLUMN mime_type text,
          ADD COLUMN acl jsonb,
          ADD COLUMN acl_synced_at timestamptz,
          ADD COLUMN last_modified_external timestamptz,
          ADD COLUMN deleted_at timestamptz;

        CREATE UNIQUE INDEX episode_connector_external_id_idx
          ON episode(workspace_id, connector_instance_id, external_id)
          WHERE connector_instance_id IS NOT NULL AND deleted_at IS NULL;

        CREATE INDEX episode_connector_idx
          ON episode(connector_instance_id, last_modified_external DESC)
          WHERE connector_instance_id IS NOT NULL AND deleted_at IS NULL;
        """
    )

    # ------------------------------------------------------------------
    # episode_acl — normalized projection of episode.acl for indexed lookup.
    #
    # The visibility CTE joins this against user_external_identity. JSONB
    # array predicates (jsonb_array_elements + ->>) won't use indexes
    # well; this normalization is the price of a fast filter.
    #
    # Rebuilt in the same transaction as each episode upsert. workspace_id
    # is denormalized so RLS can enforce isolation on the table directly.
    # ------------------------------------------------------------------
    # NULLS NOT DISTINCT lets us treat NULL principal_external_id (used by
    # 'anyone') as equal to NULL for uniqueness, instead of always-distinct.
    # A surrogate PK avoids PG's PRIMARY KEY restriction against expressions.
    op.execute(
        """
        CREATE TABLE episode_acl (
          id bigserial PRIMARY KEY,
          episode_id uuid NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          principal_kind text NOT NULL
            CHECK (principal_kind IN ('user','group','domain','anyone')),
          principal_external_id text,
          role text,
          UNIQUE NULLS NOT DISTINCT (episode_id, principal_kind, principal_external_id)
        );
        CREATE INDEX episode_acl_lookup_idx
          ON episode_acl(workspace_id, principal_kind, principal_external_id);
        CREATE INDEX episode_acl_episode_idx ON episode_acl(episode_id);
        """
    )

    # ------------------------------------------------------------------
    # agent_token — add kind discriminator.
    #
    # 'service' preserves existing behavior: token authenticates as a
    # workspace-bound principal that bypasses per-source ACLs (relies on
    # workspace RLS only). Crawler workers use these.
    #
    # 'user' is the new kind: token authenticates as a real user, the ACL
    # filter applies. These tokens are pasted into Claude Code / Cursor /
    # ChatGPT MCP configs.
    #
    # The user_id column stays NOT NULL and continues pointing at the
    # token's creator (audit trail). For 'user' tokens, user_id == the
    # principal identity. For 'service' tokens, user_id is the human who
    # provisioned the service token; the principal acts on behalf of the
    # workspace, not the human, but we keep the human attached for audit.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE agent_token
          ADD COLUMN kind text NOT NULL DEFAULT 'service'
            CHECK (kind IN ('user','service'));
        CREATE INDEX agent_token_kind_idx ON agent_token(kind, workspace_id);
        """
    )

    # ------------------------------------------------------------------
    # RLS for new workspace-scoped tables.
    #
    # Pattern matches the rest of the schema: NULL current_workspace_id
    # means "no workspace selected yet" (e.g. token resolution before we
    # know which workspace to scope to) — those queries see all rows.
    # Once a workspace is set, every row must match.
    # ------------------------------------------------------------------
    for table in ("connector_instance", "user_external_identity", "episode_acl"):
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
    op.execute("ALTER TABLE agent_token DROP COLUMN IF EXISTS kind")
    op.execute("DROP TABLE IF EXISTS episode_acl CASCADE")
    op.execute(
        """
        ALTER TABLE episode
          DROP COLUMN IF EXISTS deleted_at,
          DROP COLUMN IF EXISTS last_modified_external,
          DROP COLUMN IF EXISTS acl_synced_at,
          DROP COLUMN IF EXISTS acl,
          DROP COLUMN IF EXISTS mime_type,
          DROP COLUMN IF EXISTS content_hash,
          DROP COLUMN IF EXISTS external_revision_id,
          DROP COLUMN IF EXISTS external_url,
          DROP COLUMN IF EXISTS external_id,
          DROP COLUMN IF EXISTS connector_instance_id;
        """
    )
    op.execute("DROP TABLE IF EXISTS user_external_identity CASCADE")
    op.execute("DROP TABLE IF EXISTS connector_instance CASCADE")
