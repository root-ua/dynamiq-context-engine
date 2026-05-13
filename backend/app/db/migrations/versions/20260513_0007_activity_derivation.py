"""Activity-to-activity derivation links.

Revision ID: 20260513_0007
Revises: 20260513_0006
Create Date: 2026-05-13

Phase O3 of RFC-001 v3 alignment.

PROV-O already gives us *one* `prov:Activity` per producer
(``prov_activity``). When agent B writes a fact citing agent A's work,
the natural shape is ``B.activity wasInformedBy A.activity`` — a
many-to-many link between activities, not between entities.

We model it as a small join table rather than denormalising onto
``prov_activity``: a derived activity may cite multiple upstream
activities, and we want fast walks in both directions (downstream from
A and upstream from B). ``derivation_kind`` distinguishes the variants
PROV-O carries:

* ``derived``  → general "I used this".
* ``revised``  → I corrected this fact (the action layer uses it for
  ``attach_evidence_to_fact``).
* ``quoted``   → I copied without transformation.

Workspace-scoped so deletion cascades cleanly.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0007"
down_revision: str | None = "20260513_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE prov_activity_derivation (
          workspace_id uuid NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
          derived_activity_id uuid NOT NULL REFERENCES prov_activity(id) ON DELETE CASCADE,
          upstream_activity_id uuid NOT NULL REFERENCES prov_activity(id) ON DELETE CASCADE,
          derivation_kind text NOT NULL DEFAULT 'derived'
            CHECK (derivation_kind IN ('derived','revised','quoted')),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (derived_activity_id, upstream_activity_id),
          CHECK (derived_activity_id <> upstream_activity_id)
        );
        CREATE INDEX prov_activity_derivation_upstream_idx
          ON prov_activity_derivation(upstream_activity_id);
        CREATE INDEX prov_activity_derivation_workspace_idx
          ON prov_activity_derivation(workspace_id);
        """
    )

    op.execute("ALTER TABLE prov_activity_derivation ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY prov_activity_derivation_ws_select
          ON prov_activity_derivation FOR SELECT
          USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
        CREATE POLICY prov_activity_derivation_ws_modify
          ON prov_activity_derivation FOR ALL
          USING (current_workspace_id() IS NULL OR workspace_id = current_workspace_id())
          WITH CHECK (current_workspace_id() IS NULL OR workspace_id = current_workspace_id());
        """
    )
    op.execute(
        "ALTER TABLE prov_activity_derivation FORCE ROW LEVEL SECURITY"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prov_activity_derivation CASCADE")
