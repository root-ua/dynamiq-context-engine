"""Unified external-ACL enforcement via Postgres Row Level Security.

Before this migration, source-ACL filtering was scattered across ~10
application call sites (hybrid retrieval, graph traversal, REST list
endpoints, MCP tools, provenance). Each new read path was a potential
leak; we shipped at least three of them before tightening up.

This migration moves enforcement into the database, matching the
existing workspace RLS pattern. After it lands:

* `app.current_user_email` + `app.current_user_domain` GUCs are set
  by ``session_scope`` from the JWT principal.
* `app.bypass_external_acl = 'true'` flips a kill-switch for service
  callers (crawler workers, agent tokens with kind='service') and
  any privileged admin endpoint (permissions inspector, exports).
* Restrictive policies on `episode`, `edge`, `entity` reject rows
  the GUC-identified user cannot see — regardless of which Python
  code path issued the query.

Helper functions are PL/SQL `STABLE` so the optimizer can fold them
into the query plan; the existing per-row LEFT JOIN approach used in
the application code was already comparable, and the indexes added
in 20260520_0001 (ws+email, ws+domain) still apply.

Inserts and updates are NOT restricted — only SELECT. Two reasons:

1. The extraction pipeline writes edges with `source_id` pointing to
   the episode the LLM extracted from. The caller's identity may not
   match the doc's ACL (the sync worker is acting as a system agent).
   Blocking the insert would break ingestion.
2. The Drive sync worker writes ACL rows on behalf of the doc owner.
   We don't want write-side gating; we want read-side gating.

Service callers and the sync worker should still set
`bypass_external_acl=true` for reads they do during work.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260521_0001"
down_revision: str | None = "20260520_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Non-superuser app role.
    #
    # Postgres RLS is silently bypassed when the connecting role has
    # `rolbypassrls=t` (the default for superusers and the bootstrap
    # account). The `memory` user that the app connects as is a
    # superuser, so the existing workspace RLS policies and our new
    # external-ACL policies are inert by default — explicit
    # WHERE-clauses in app code have been doing all the filtering.
    #
    # To make RLS actually enforce, we create a non-superuser /
    # non-bypassrls role here and have ``session_scope`` issue
    # ``SET LOCAL ROLE memory_app`` at the start of every transaction.
    # The connecting superuser can drop into any role it owns; the
    # drop is scoped to the transaction so admin DDL still runs as
    # the superuser.
    #
    # Grants mirror what the app already needs (ALL on every table +
    # sequence + function in public). Default privileges are also set
    # so future migrations don't need to re-grant.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'memory_app') THEN
            CREATE ROLE memory_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
          END IF;
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO memory_app")
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO memory_app")
    op.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO memory_app")
    op.execute("GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO memory_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL ON TABLES TO memory_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL ON SEQUENCES TO memory_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL ON FUNCTIONS TO memory_app"
    )

    # ------------------------------------------------------------------
    # GUC accessor helpers. Same shape as current_workspace_id() — a
    # STABLE plpgsql function that reads the session-local setting and
    # NULLs out on absent/empty values.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_user_email()
        RETURNS citext
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
          RETURN nullif(current_setting('app.current_user_email', true), '')::citext;
        EXCEPTION WHEN others THEN
          RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_user_domain()
        RETURNS citext
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
          RETURN nullif(current_setting('app.current_user_domain', true), '')::citext;
        EXCEPTION WHEN others THEN
          RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bypass_external_acl()
        RETURNS boolean
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
          RETURN COALESCE(
            current_setting('app.bypass_external_acl', true) = 'true',
            false
          );
        EXCEPTION WHEN others THEN
          RETURN false;
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # Visibility predicates. Each takes the row's identifier(s) and
    # returns a boolean. Keep them SQL (not plpgsql) so the planner can
    # inline them — these run inside RLS policies on every SELECT and
    # need to be as cheap as possible.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION episode_visible_to_me(eid uuid)
        RETURNS boolean
        LANGUAGE sql STABLE AS $$
          SELECT bypass_external_acl()
              OR current_user_email() IS NULL
              OR NOT EXISTS (
                   SELECT 1 FROM episode_external_acl x
                   WHERE x.episode_id = eid
                 )
              OR EXISTS (
                   SELECT 1 FROM episode_external_acl ea
                   WHERE ea.episode_id = eid AND (
                     ea.ace_kind = 'anyone'
                     OR (ea.ace_kind = 'domain'
                         AND ea.domain = current_user_domain())
                     OR (ea.ace_kind IN ('user','group')
                         AND ea.email = current_user_email())
                   )
                 );
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION edge_visible_to_me(
            src_id uuid, src_kind text
        )
        RETURNS boolean
        LANGUAGE sql STABLE AS $$
          SELECT bypass_external_acl()
              OR current_user_email() IS NULL
              OR src_id IS NULL
              OR src_kind IS DISTINCT FROM 'episode'
              OR episode_visible_to_me(src_id);
        $$;
        """
    )
    # Entity visibility: visible iff at least one attaching edge is
    # visible to the caller. The nested edge query uses the edge RLS
    # policy added below, so it automatically sees only the visible
    # subset.
    #
    # Notable: no "orphan exception". An entity whose edges are all
    # hidden by RLS would otherwise look orphan to the caller and slip
    # through. The stricter rule means entities created exclusively
    # by extraction of a confidential doc remain hidden even when
    # their edges get filtered out one-by-one.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION entity_visible_to_me(eid uuid)
        RETURNS boolean
        LANGUAGE sql STABLE AS $$
          SELECT bypass_external_acl()
              OR current_user_email() IS NULL
              OR EXISTS (
                   SELECT 1 FROM edge
                   WHERE subject_id = eid OR object_id = eid
                 );
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RESTRICTIVE RLS policies. Postgres ANDs restrictive policies with
    # the existing permissive workspace policies, so a row is visible
    # only if BOTH workspace AND source ACL allow it.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE POLICY episode_external_acl_select
          ON episode AS RESTRICTIVE FOR SELECT
          USING (episode_visible_to_me(id));
        """
    )
    op.execute(
        """
        CREATE POLICY edge_external_acl_select
          ON edge AS RESTRICTIVE FOR SELECT
          USING (edge_visible_to_me(source_id, source_kind));
        """
    )
    op.execute(
        """
        CREATE POLICY entity_external_acl_select
          ON entity AS RESTRICTIVE FOR SELECT
          USING (entity_visible_to_me(id));
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS entity_external_acl_select ON entity")
    op.execute("DROP POLICY IF EXISTS edge_external_acl_select ON edge")
    op.execute("DROP POLICY IF EXISTS episode_external_acl_select ON episode")
    op.execute("DROP FUNCTION IF EXISTS entity_visible_to_me(uuid)")
    op.execute("DROP FUNCTION IF EXISTS edge_visible_to_me(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS episode_visible_to_me(uuid)")
    op.execute("DROP FUNCTION IF EXISTS bypass_external_acl()")
    op.execute("DROP FUNCTION IF EXISTS current_user_domain()")
    op.execute("DROP FUNCTION IF EXISTS current_user_email()")
    # Drop role last; revoke first to satisfy dependencies.
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM memory_app")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM memory_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM memory_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM memory_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM memory_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL ON SEQUENCES FROM memory_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL ON FUNCTIONS FROM memory_app"
    )
    op.execute("DROP ROLE IF EXISTS memory_app")
