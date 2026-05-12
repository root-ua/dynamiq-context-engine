"""initial schema: tenancy, ontology, bi-temporal graph, documents, ingestion, audit

Revision ID: 20260421_0001
Revises:
Create Date: 2026-04-21

Creates the full schema in one pass so the bi-temporal semantics and RLS
policies are consistent from the first write.

Embedding dimension is hardcoded to 1536 (matches text-embedding-3-small).
Changing embedding models later requires a column-alter migration.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260421_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMBEDDING_DIM = 1536


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions (idempotent; also loaded by ops/postgres/init.sql).
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # Reusable helpers
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_workspace_id() RETURNS uuid AS $$
        BEGIN
          RETURN nullif(current_setting('app.current_workspace_id', true), '')::uuid;
        EXCEPTION WHEN others THEN
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_user_id() RETURNS uuid AS $$
        BEGIN
          RETURN nullif(current_setting('app.current_user_id', true), '')::uuid;
        EXCEPTION WHEN others THEN
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE;
        """
    )

    # ------------------------------------------------------------------
    # Tenancy
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE workspace (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          slug text NOT NULL UNIQUE,
          name text NOT NULL,
          settings jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz
        );
        CREATE TRIGGER workspace_updated_at BEFORE UPDATE ON workspace
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TABLE app_user (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          email citext NOT NULL UNIQUE,
          name text,
          password_hash text,
          avatar_url text,
          is_active boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TRIGGER app_user_updated_at BEFORE UPDATE ON app_user
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TABLE workspace_member (
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          role text NOT NULL CHECK (role IN ('owner','admin','editor','viewer')),
          joined_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (workspace_id, user_id)
        );
        CREATE INDEX workspace_member_user_idx ON workspace_member(user_id);
        """
    )

    # ------------------------------------------------------------------
    # Ontology: entity types and relation types
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE entity_type (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid REFERENCES workspace(id) ON DELETE CASCADE,
          name text NOT NULL,
          slug text NOT NULL,
          extends_id uuid REFERENCES entity_type(id),
          hierarchy ltree NOT NULL,
          schema jsonb NOT NULL DEFAULT '{"type":"object","properties":{}}'::jsonb,
          ui_hints jsonb NOT NULL DEFAULT '{}'::jsonb,
          description text,
          system boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz,
          UNIQUE (workspace_id, slug)
        );
        CREATE INDEX entity_type_hierarchy_gist ON entity_type USING gist (hierarchy);
        CREATE INDEX entity_type_workspace_idx ON entity_type(workspace_id);
        CREATE TRIGGER entity_type_updated_at BEFORE UPDATE ON entity_type
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # Trigger to maintain `hierarchy` from `extends_id` (materialized path).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION entity_type_set_hierarchy() RETURNS TRIGGER AS $$
        DECLARE
          parent_hierarchy ltree;
        BEGIN
          IF NEW.extends_id IS NULL THEN
            NEW.hierarchy := text2ltree(regexp_replace(NEW.slug, '[^a-z0-9_]', '_', 'g'));
          ELSE
            SELECT hierarchy INTO parent_hierarchy FROM entity_type WHERE id = NEW.extends_id;
            IF parent_hierarchy IS NULL THEN
              RAISE EXCEPTION 'parent entity_type % not found', NEW.extends_id;
            END IF;
            NEW.hierarchy := parent_hierarchy || text2ltree(regexp_replace(NEW.slug, '[^a-z0-9_]', '_', 'g'));
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER entity_type_hierarchy_ins BEFORE INSERT ON entity_type
          FOR EACH ROW EXECUTE FUNCTION entity_type_set_hierarchy();
        CREATE TRIGGER entity_type_hierarchy_upd BEFORE UPDATE OF extends_id, slug ON entity_type
          FOR EACH ROW EXECUTE FUNCTION entity_type_set_hierarchy();
        """
    )

    op.execute(
        """
        CREATE TABLE relation_type (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid REFERENCES workspace(id) ON DELETE CASCADE,
          name text NOT NULL,
          slug text NOT NULL,
          description text,
          domain_type_id uuid REFERENCES entity_type(id),
          range_type_id uuid REFERENCES entity_type(id),
          cardinality_subject text NOT NULL DEFAULT 'many' CHECK (cardinality_subject IN ('one','many')),
          cardinality_object text NOT NULL DEFAULT 'many' CHECK (cardinality_object IN ('one','many')),
          inverse_of_id uuid REFERENCES relation_type(id),
          "symmetric" boolean NOT NULL DEFAULT false,
          transitive boolean NOT NULL DEFAULT false,
          temporal boolean NOT NULL DEFAULT true,
          high_stakes boolean NOT NULL DEFAULT false,
          ui_hints jsonb NOT NULL DEFAULT '{}'::jsonb,
          system boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz,
          UNIQUE (workspace_id, slug)
        );
        CREATE INDEX relation_type_workspace_idx ON relation_type(workspace_id);
        CREATE TRIGGER relation_type_updated_at BEFORE UPDATE ON relation_type
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ------------------------------------------------------------------
    # Graph: entities (uni-temporal) and edges (bi-temporal)
    # ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE entity (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          type_id uuid NOT NULL REFERENCES entity_type(id),
          iri text NOT NULL,
          canonical text NOT NULL,
          aliases text[] NOT NULL DEFAULT '{{}}',
          summary text,
          summary_embedding vector({EMBEDDING_DIM}),
          props jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          merged_into_id uuid REFERENCES entity(id),
          created_by uuid REFERENCES app_user(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz,
          UNIQUE (workspace_id, iri)
        );
        CREATE INDEX entity_workspace_type_idx ON entity(workspace_id, type_id);
        CREATE INDEX entity_canonical_trgm ON entity USING gin (canonical gin_trgm_ops);
        CREATE INDEX entity_aliases_gin ON entity USING gin (aliases);
        CREATE INDEX entity_props_gin ON entity USING gin (props jsonb_path_ops);
        CREATE INDEX entity_merged_into_idx ON entity(merged_into_id) WHERE merged_into_id IS NOT NULL;
        CREATE TRIGGER entity_updated_at BEFORE UPDATE ON entity
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    # HNSW on embeddings — only built once data exists; index is still declared now.
    op.execute(
        """
        CREATE INDEX entity_summary_embedding_hnsw ON entity
          USING hnsw (summary_embedding vector_cosine_ops)
          WITH (m = 16, ef_construction = 64)
          WHERE summary_embedding IS NOT NULL;
        """
    )

    op.execute(
        f"""
        CREATE TABLE edge (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          subject_id uuid NOT NULL REFERENCES entity(id),
          predicate_id uuid NOT NULL REFERENCES relation_type(id),
          object_id uuid NOT NULL REFERENCES entity(id),
          fact text NOT NULL,
          fact_embedding vector({EMBEDDING_DIM}),
          props jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          valid_time tstzrange NOT NULL DEFAULT tstzrange(now(), 'infinity', '[)'),
          sys_time tstzrange NOT NULL DEFAULT tstzrange(now(), 'infinity', '[)'),
          source_id uuid,
          source_kind text,
          confidence real,
          invalidated_by uuid REFERENCES edge(id),
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK (NOT isempty(valid_time)),
          CHECK (NOT isempty(sys_time))
        );
        CREATE INDEX edge_workspace_idx ON edge(workspace_id);
        CREATE INDEX edge_subject_live_idx ON edge(subject_id, predicate_id)
          WHERE upper(sys_time) = 'infinity';
        CREATE INDEX edge_object_live_idx ON edge(object_id, predicate_id)
          WHERE upper(sys_time) = 'infinity';
        CREATE INDEX edge_valid_time_gist ON edge USING gist (valid_time);
        CREATE INDEX edge_sys_time_gist ON edge USING gist (sys_time);
        CREATE INDEX edge_subject_predicate_valid_gist ON edge
          USING gist (subject_id, predicate_id, valid_time)
          WHERE upper(sys_time) = 'infinity';
        CREATE INDEX edge_source_idx ON edge(source_id) WHERE source_id IS NOT NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX edge_fact_embedding_hnsw ON edge
          USING hnsw (fact_embedding vector_cosine_ops)
          WITH (m = 16, ef_construction = 64)
          WHERE fact_embedding IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE entity_attribute (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          entity_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          name text NOT NULL,
          value jsonb NOT NULL,
          valid_time tstzrange NOT NULL DEFAULT tstzrange(now(), 'infinity', '[)'),
          sys_time tstzrange NOT NULL DEFAULT tstzrange(now(), 'infinity', '[)'),
          source_id uuid,
          confidence real,
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK (NOT isempty(valid_time)),
          CHECK (NOT isempty(sys_time))
        );
        CREATE INDEX entity_attribute_entity_idx ON entity_attribute(entity_id, name);
        CREATE INDEX entity_attribute_live_idx ON entity_attribute(entity_id, name)
          WHERE upper(sys_time) = 'infinity';
        CREATE INDEX entity_attribute_valid_gist ON entity_attribute USING gist (valid_time);
        """
    )

    # ------------------------------------------------------------------
    # Documents: blocks + Yjs state
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE document (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          entity_id uuid NOT NULL UNIQUE REFERENCES entity(id) ON DELETE CASCADE,
          yjs_state bytea,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX document_workspace_idx ON document(workspace_id);
        CREATE TRIGGER document_updated_at BEFORE UPDATE ON document
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TABLE block (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          document_id uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
          parent_block_id uuid REFERENCES block(id) ON DELETE CASCADE,
          position numeric(40, 20) NOT NULL,
          block_type text NOT NULL,
          content jsonb NOT NULL DEFAULT '{}'::jsonb,
          props jsonb NOT NULL DEFAULT '{}'::jsonb,
          version integer NOT NULL DEFAULT 1,
          search_text text,
          search_tsv tsvector GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(search_text, ''))
          ) STORED,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz
        );
        CREATE INDEX block_document_position_idx ON block(document_id, position)
          WHERE deleted_at IS NULL;
        CREATE INDEX block_parent_idx ON block(parent_block_id) WHERE deleted_at IS NULL;
        CREATE INDEX block_workspace_idx ON block(workspace_id);
        CREATE INDEX block_search_tsv_gin ON block USING gin (search_tsv);
        CREATE TRIGGER block_updated_at BEFORE UPDATE ON block
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TABLE block_entity_ref (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          block_id uuid NOT NULL REFERENCES block(id) ON DELETE CASCADE,
          entity_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          mention_type text NOT NULL DEFAULT 'mention',
          position integer NOT NULL DEFAULT 0,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (block_id, entity_id, position)
        );
        CREATE INDEX block_entity_ref_block_idx ON block_entity_ref(block_id);
        CREATE INDEX block_entity_ref_entity_idx ON block_entity_ref(entity_id);
        """
    )

    # ------------------------------------------------------------------
    # Ingestion: episodes (non-lossy ground truth)
    # ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE episode (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          source_kind text NOT NULL,
          source_ref text,
          occurred_at timestamptz NOT NULL,
          ingested_at timestamptz NOT NULL DEFAULT now(),
          content jsonb NOT NULL,
          content_text text,
          content_embedding vector({EMBEDDING_DIM}),
          processing_status text NOT NULL DEFAULT 'pending'
            CHECK (processing_status IN ('pending','processing','completed','failed')),
          processing_error text,
          created_by uuid REFERENCES app_user(id)
        );
        CREATE INDEX episode_workspace_occurred_idx ON episode(workspace_id, occurred_at DESC);
        CREATE INDEX episode_status_idx ON episode(processing_status)
          WHERE processing_status IN ('pending','processing');
        CREATE INDEX episode_content_text_trgm ON episode USING gin (content_text gin_trgm_ops)
          WHERE content_text IS NOT NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX episode_content_embedding_hnsw ON episode
          USING hnsw (content_embedding vector_cosine_ops)
          WITH (m = 16, ef_construction = 64)
          WHERE content_embedding IS NOT NULL;
        """
    )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE agent_session (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          user_id uuid REFERENCES app_user(id),
          client text,
          started_at timestamptz NOT NULL DEFAULT now(),
          ended_at timestamptz
        );
        CREATE INDEX agent_session_workspace_idx ON agent_session(workspace_id, started_at DESC);
        """
    )

    op.execute(
        """
        CREATE TABLE agent_tool_call (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          session_id uuid REFERENCES agent_session(id) ON DELETE CASCADE,
          tool text NOT NULL,
          input jsonb NOT NULL,
          output jsonb,
          error text,
          latency_ms integer,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX agent_tool_call_session_idx ON agent_tool_call(session_id, created_at DESC);
        CREATE INDEX agent_tool_call_tool_idx ON agent_tool_call(workspace_id, tool, created_at DESC);
        """
    )

    op.execute(
        """
        CREATE TABLE audit_log (
          id bigserial PRIMARY KEY,
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          actor_kind text NOT NULL CHECK (actor_kind IN ('user','agent','system')),
          actor_id uuid,
          action text NOT NULL,
          target_kind text NOT NULL,
          target_id uuid,
          diff jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX audit_log_workspace_idx ON audit_log(workspace_id, created_at DESC);
        CREATE INDEX audit_log_target_idx ON audit_log(target_kind, target_id);
        """
    )

    # ------------------------------------------------------------------
    # Row-level security: every workspace-scoped table
    # ------------------------------------------------------------------
    workspace_scoped = [
        "workspace",  # self-gated
        "entity_type",
        "relation_type",
        "entity",
        "edge",
        "entity_attribute",
        "document",
        "block",
        "block_entity_ref",
        "episode",
        "agent_session",
        "agent_tool_call",
        "audit_log",
    ]

    for table in workspace_scoped:
        scope_col = "id" if table == "workspace" else "workspace_id"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_ws_select ON {table} FOR SELECT
              USING (current_workspace_id() IS NULL OR {scope_col} = current_workspace_id());
            CREATE POLICY {table}_ws_modify ON {table} FOR ALL
              USING (current_workspace_id() IS NULL OR {scope_col} = current_workspace_id())
              WITH CHECK (current_workspace_id() IS NULL OR {scope_col} = current_workspace_id());
            """
        )
        # Force RLS for non-owner roles. The backend connects as a non-superuser;
        # this prevents the BYPASSRLS attribute from accidentally leaking.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Shared tables (user, workspace_member) are gated at app layer; keep RLS off
    # so auth flows can operate before a workspace is selected.

    # ------------------------------------------------------------------
    # Inverse-edge auto-mirror trigger
    # Writes a single inverse row atomically when predicate has inverse_of_id set.
    # Uses a session-level guard to avoid infinite recursion.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION edge_mirror_inverse() RETURNS TRIGGER AS $$
        DECLARE
          inv_pred uuid;
          sym boolean;
          guard text;
        BEGIN
          guard := current_setting('app.edge_mirror_active', true);
          IF guard = 'on' THEN
            RETURN NEW;
          END IF;

          SELECT inverse_of_id, "symmetric" INTO inv_pred, sym
            FROM relation_type WHERE id = NEW.predicate_id;

          PERFORM set_config('app.edge_mirror_active', 'on', true);

          IF sym AND NEW.subject_id <> NEW.object_id THEN
            INSERT INTO edge (
              workspace_id, subject_id, predicate_id, object_id,
              fact, fact_embedding, props, valid_time, sys_time,
              source_id, source_kind, confidence, created_by
            ) VALUES (
              NEW.workspace_id, NEW.object_id, NEW.predicate_id, NEW.subject_id,
              NEW.fact, NEW.fact_embedding, NEW.props, NEW.valid_time, NEW.sys_time,
              NEW.source_id, NEW.source_kind, NEW.confidence, NEW.created_by
            );
          ELSIF inv_pred IS NOT NULL THEN
            INSERT INTO edge (
              workspace_id, subject_id, predicate_id, object_id,
              fact, fact_embedding, props, valid_time, sys_time,
              source_id, source_kind, confidence, created_by
            ) VALUES (
              NEW.workspace_id, NEW.object_id, inv_pred, NEW.subject_id,
              NEW.fact, NEW.fact_embedding, NEW.props, NEW.valid_time, NEW.sys_time,
              NEW.source_id, NEW.source_kind, NEW.confidence, NEW.created_by
            );
          END IF;

          PERFORM set_config('app.edge_mirror_active', 'off', true);
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER edge_mirror_inverse_tg
          AFTER INSERT ON edge
          FOR EACH ROW EXECUTE FUNCTION edge_mirror_inverse();
        """
    )


def downgrade() -> None:
    # Full teardown for dev convenience. Not intended for production.
    for table in [
        "audit_log",
        "agent_tool_call",
        "agent_session",
        "episode",
        "block_entity_ref",
        "block",
        "document",
        "entity_attribute",
        "edge",
        "entity",
        "relation_type",
        "entity_type",
        "workspace_member",
        "app_user",
        "workspace",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    for fn in [
        "edge_mirror_inverse",
        "entity_type_set_hierarchy",
        "set_updated_at",
        "current_workspace_id",
        "current_user_id",
    ]:
        op.execute(f"DROP FUNCTION IF EXISTS {fn} CASCADE")
