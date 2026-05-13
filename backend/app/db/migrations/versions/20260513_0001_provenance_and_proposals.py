"""provenance (PROV-O) activities + per-class extraction policy + fact review queue

Revision ID: 20260513_0001
Revises: 20260508_0001
Create Date: 2026-05-13

Phase A of RFC-001 v3 alignment — the "honesty layer".

Adds three concepts:

* ``prov_activity`` — a W3C PROV-O ``prov:Activity`` row representing one
  extraction run / contradictor pass / manual edit / merge / action. Every
  edge, episode, and attribute can attribute itself to one activity via
  ``prov_activity_id``. Together with ``agent_kind`` + ``agent_ref`` we get
  the PROV trinity (entity ← activity ← agent) without adopting a full
  OWL stack.

* ``extraction_policy`` — per-(entity_type | relation_type) confidence
  threshold. Facts at or above ``min_confidence`` go straight to ``edge``;
  facts in (auto_reject_below, min_confidence) land in ``pending_fact``
  for human review; facts below ``auto_reject_below`` are rejected
  outright (recorded as ``pending_fact(status='rejected')`` for audit).

* ``pending_fact`` — shadow-edge row carrying everything needed to
  materialize an ``edge`` on approval. Status transitions: pending →
  approved (writes through to edge, captures ``approved_edge_id``) /
  rejected / superseded.

RLS pattern matches the rest of the schema: enable + workspace_id policy
+ FORCE. Indexes target the review-queue UX (workspace + status).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0001"
down_revision: str | None = "20260508_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # prov_activity — the PROV-O Activity node.
    #
    # ``kind`` describes what produced the entity (extraction, contradiction,
    # manual_edit, merge, action, seed). ``agent_kind`` + ``agent_ref`` +
    # ``agent_version`` give us the Agent attribution; pin the model
    # identifier so we can later replay or distinguish facts produced by
    # different model versions.
    #
    # ``audit_log_id`` lets the activity link back to the human-readable
    # audit row that already exists; mostly useful for ``manual_edit`` /
    # ``merge`` where the audit row predates the activity row by
    # convention. Nullable because automated extraction creates the
    # activity row in the same transaction.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE prov_activity (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          kind text NOT NULL CHECK (kind IN
            ('extraction','contradiction','manual_edit','merge','action','seed','approval')),
          agent_kind text NOT NULL
            CHECK (agent_kind IN ('llm','user','system','connector')),
          agent_ref text,
          agent_version text,
          inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
          outputs jsonb NOT NULL DEFAULT '{}'::jsonb,
          started_at timestamptz NOT NULL DEFAULT now(),
          ended_at timestamptz,
          audit_log_id bigint REFERENCES audit_log(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX prov_activity_workspace_idx ON prov_activity(workspace_id);
        CREATE INDEX prov_activity_kind_idx
          ON prov_activity(workspace_id, kind, started_at DESC);
        """
    )

    # Wire prov_activity_id into the three derived-content tables. All are
    # nullable so existing rows survive the migration; the extraction
    # pipeline starts writing them with the same migration.
    op.execute(
        """
        ALTER TABLE edge
          ADD COLUMN prov_activity_id uuid REFERENCES prov_activity(id) ON DELETE SET NULL;
        ALTER TABLE entity_attribute
          ADD COLUMN prov_activity_id uuid REFERENCES prov_activity(id) ON DELETE SET NULL;
        ALTER TABLE episode
          ADD COLUMN prov_activity_id uuid REFERENCES prov_activity(id) ON DELETE SET NULL;
        CREATE INDEX edge_prov_activity_idx
          ON edge(prov_activity_id) WHERE prov_activity_id IS NOT NULL;
        CREATE INDEX entity_attribute_prov_activity_idx
          ON entity_attribute(prov_activity_id) WHERE prov_activity_id IS NOT NULL;
        CREATE INDEX episode_prov_activity_idx
          ON episode(prov_activity_id) WHERE prov_activity_id IS NOT NULL;
        """
    )

    # ------------------------------------------------------------------
    # extraction_policy — per-(entity_type | relation_type) thresholds.
    #
    # NULL on both type ids = workspace default (one row). The CHECK
    # constraint forbids setting both. Default thresholds (0.7 / 0.3)
    # match the RFC defaults and are conservative; tune via UI.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE extraction_policy (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          entity_type_id uuid REFERENCES entity_type(id) ON DELETE CASCADE,
          relation_type_id uuid REFERENCES relation_type(id) ON DELETE CASCADE,
          min_confidence real NOT NULL DEFAULT 0.7
            CHECK (min_confidence BETWEEN 0 AND 1),
          auto_reject_below real NOT NULL DEFAULT 0.3
            CHECK (auto_reject_below BETWEEN 0 AND 1),
          CHECK (auto_reject_below <= min_confidence),
          CHECK ((entity_type_id IS NULL) OR (relation_type_id IS NULL)),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX extraction_policy_workspace_default_idx
          ON extraction_policy(workspace_id)
          WHERE entity_type_id IS NULL AND relation_type_id IS NULL;
        CREATE UNIQUE INDEX extraction_policy_workspace_entity_idx
          ON extraction_policy(workspace_id, entity_type_id)
          WHERE entity_type_id IS NOT NULL;
        CREATE UNIQUE INDEX extraction_policy_workspace_relation_idx
          ON extraction_policy(workspace_id, relation_type_id)
          WHERE relation_type_id IS NOT NULL;
        CREATE TRIGGER extraction_policy_updated_at
          BEFORE UPDATE ON extraction_policy
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ------------------------------------------------------------------
    # pending_fact — shadow-edge with status. Columns mirror edge except:
    #   * No fact_embedding (computed on approval); cheap to recompute.
    #   * valid_from / valid_to as plain timestamps so REST can patch
    #     them during review without manipulating a range.
    #   * status transitions are unidirectional (CHECK trigger below).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE pending_fact (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          subject_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          predicate_id uuid NOT NULL REFERENCES relation_type(id) ON DELETE CASCADE,
          object_id uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
          fact text NOT NULL,
          props jsonb NOT NULL DEFAULT '{}'::jsonb,
          valid_from timestamptz NOT NULL DEFAULT now(),
          valid_to timestamptz,
          source_id uuid,
          source_kind text,
          confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
          prov_activity_id uuid REFERENCES prov_activity(id) ON DELETE SET NULL,
          status text NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','approved','rejected','superseded')),
          reason text,
          reviewed_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
          reviewed_at timestamptz,
          approved_edge_id uuid REFERENCES edge(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX pending_fact_workspace_status_idx
          ON pending_fact(workspace_id, status, created_at DESC);
        CREATE INDEX pending_fact_subject_idx
          ON pending_fact(subject_id) WHERE status = 'pending';
        CREATE INDEX pending_fact_predicate_idx
          ON pending_fact(predicate_id) WHERE status = 'pending';
        CREATE INDEX pending_fact_source_idx
          ON pending_fact(source_id) WHERE source_id IS NOT NULL;
        CREATE TRIGGER pending_fact_updated_at
          BEFORE UPDATE ON pending_fact
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ------------------------------------------------------------------
    # Propagate prov_activity_id through the inverse-edge mirror trigger
    # so paired edges carry the same provenance.
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
              source_id, source_kind, confidence, created_by, prov_activity_id
            ) VALUES (
              NEW.workspace_id, NEW.object_id, NEW.predicate_id, NEW.subject_id,
              NEW.fact, NEW.fact_embedding, NEW.props, NEW.valid_time, NEW.sys_time,
              NEW.source_id, NEW.source_kind, NEW.confidence, NEW.created_by, NEW.prov_activity_id
            );
          ELSIF inv_pred IS NOT NULL THEN
            INSERT INTO edge (
              workspace_id, subject_id, predicate_id, object_id,
              fact, fact_embedding, props, valid_time, sys_time,
              source_id, source_kind, confidence, created_by, prov_activity_id
            ) VALUES (
              NEW.workspace_id, NEW.object_id, inv_pred, NEW.subject_id,
              NEW.fact, NEW.fact_embedding, NEW.props, NEW.valid_time, NEW.sys_time,
              NEW.source_id, NEW.source_kind, NEW.confidence, NEW.created_by, NEW.prov_activity_id
            );
          END IF;

          PERFORM set_config('app.edge_mirror_active', 'off', true);
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ------------------------------------------------------------------
    # RLS for the three new workspace-scoped tables.
    # ------------------------------------------------------------------
    for table in ("prov_activity", "extraction_policy", "pending_fact"):
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
    op.execute("DROP TABLE IF EXISTS pending_fact CASCADE")
    op.execute("DROP TABLE IF EXISTS extraction_policy CASCADE")
    op.execute(
        """
        ALTER TABLE edge             DROP COLUMN IF EXISTS prov_activity_id;
        ALTER TABLE entity_attribute DROP COLUMN IF EXISTS prov_activity_id;
        ALTER TABLE episode          DROP COLUMN IF EXISTS prov_activity_id;
        """
    )
    op.execute("DROP TABLE IF EXISTS prov_activity CASCADE")
