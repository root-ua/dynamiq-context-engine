"""Edges — the actual knowledge graph structure.

Every edge here has a realistic `valid_from`; many have `valid_to` too
(past relationships). Two edges have `invalidate_at` set: that's how we
model "we believed X, then learned Y contradicts it" — the seeder
inserts the edge and then invalidates it at the given timestamp.

Relation slugs:
  - `works_at`         (person → organization)  — built-in
  - `manages`          (person → agent)         — built-in
  - `authored`         (person → content)       — built-in
  - `member_of`        (agent → agent)          — built-in
  - `part_of`          (work → work)            — built-in
  - `funded_by`        (organization → organization) — workspace-scoped
  - `customer_of`      (organization → organization) — workspace-scoped
  - `works_on`         (person → project)       — workspace-scoped
"""

from datetime import UTC, datetime

from seeds.demo.halcyon._types import EdgeSeed


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


EDGES: tuple[EdgeSeed, ...] = (
    # ---------- Founders + early hires ----------
    EdgeSeed(
        subject_key="person.sarah_chen",
        predicate="works_at",
        object_key="org.halcyon",
        fact="Sarah Chen works at Halcyon Labs as CEO.",
        valid_from=_dt(2025, 1, 6),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.sarah_chen",
        predicate="manages",
        object_key="org.halcyon",
        fact="Sarah Chen leads Halcyon Labs.",
        valid_from=_dt(2025, 1, 6),
        source_kind="manual",
    ),
    # --- Alex's role history: bi-temporal, two non-overlapping ranges ---
    EdgeSeed(
        subject_key="person.alex_park",
        predicate="works_at",
        object_key="org.halcyon",
        fact="Alex Park joined Halcyon as Founding Engineer.",
        valid_from=_dt(2025, 1, 6),
        valid_to=_dt(2025, 7, 14),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.alex_park",
        predicate="works_at",
        object_key="org.halcyon",
        fact="Alex Park promoted to Head of Engineering.",
        valid_from=_dt(2025, 7, 14),
        source_kind="document",
        source_ref_key="doc.strategy_memo_2026",
    ),
    EdgeSeed(
        subject_key="person.priya_raghavan",
        predicate="works_at",
        object_key="org.halcyon",
        fact="Priya Raghavan joined as founding designer.",
        valid_from=_dt(2025, 2, 17),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.marcus_webb",
        predicate="works_at",
        object_key="org.halcyon",
        fact="Marcus Webb joined as first AE.",
        valid_from=_dt(2025, 8, 4),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.elena_kowalczyk",
        predicate="works_at",
        object_key="org.halcyon",
        fact="Elena Kowalczyk joined as engineer #3.",
        valid_from=_dt(2025, 8, 18),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.jordan_reyes",
        predicate="works_at",
        object_key="org.zephyr_data",
        fact="Jordan Reyes is staff eng at Zephyr Data.",
        valid_from=_dt(2024, 6, 1),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.mira_okonkwo",
        predicate="works_at",
        object_key="org.atlas_ventures",
        fact="Mira Okonkwo is a partner at Atlas Ventures.",
        valid_from=_dt(2021, 3, 1),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="person.hana_lindqvist",
        predicate="works_at",
        object_key="org.glass_ridge",
        fact="Hana Lindqvist is a partner at Glass Ridge Capital.",
        valid_from=_dt(2023, 9, 1),
        source_kind="manual",
    ),
    # ---------- Funding ----------
    EdgeSeed(
        subject_key="org.halcyon",
        predicate="funded_by",
        object_key="org.atlas_ventures",
        fact="Halcyon Labs raised $4M seed from Atlas Ventures.",
        valid_from=_dt(2025, 3, 10),
        source_kind="manual",
    ),
    # --- Contradiction #1: the $20M target that got revised down. ---
    # Inserted as of Dec 15, 2025. Invalidated Feb 6, 2026 when the actual
    # (smaller) Series A closed.
    EdgeSeed(
        subject_key="org.halcyon",
        predicate="funded_by",
        object_key="org.glass_ridge",
        fact="Halcyon is targeting a $20M Series A led by Glass Ridge.",
        valid_from=_dt(2025, 12, 15),
        confidence=0.7,  # a "target", not closed
        source_kind="agent",
        invalidate_at=_dt(2026, 2, 6),
        invalidate_reason="Round closed at $15M, not $20M.",
    ),
    EdgeSeed(
        subject_key="org.halcyon",
        predicate="funded_by",
        object_key="org.glass_ridge",
        fact="Halcyon Labs closed $15M Series A led by Glass Ridge.",
        valid_from=_dt(2026, 2, 6),
        source_kind="document",
        source_ref_key="doc.strategy_memo_2026",
    ),
    # ---------- Customer relationship ----------
    # --- Contradiction #2: Zephyr LOI → pulled → contract. ---
    EdgeSeed(
        subject_key="org.zephyr_data",
        predicate="customer_of",
        object_key="org.halcyon",
        fact="Zephyr Data signed a Letter of Intent to pilot Orbit.",
        valid_from=_dt(2025, 9, 23),
        confidence=0.85,  # not yet a signed contract
        source_kind="manual",
        invalidate_at=_dt(2025, 10, 14),
        invalidate_reason=(
            "LOI withdrawn after eval-accuracy issue surfaced during pilot "
            "(see Zephyr pilot postmortem)."
        ),
    ),
    EdgeSeed(
        subject_key="org.zephyr_data",
        predicate="customer_of",
        object_key="org.halcyon",
        fact="Zephyr Data signed 1-year Orbit contract ($84K ACV).",
        valid_from=_dt(2025, 11, 19),
        valid_to=_dt(2026, 11, 19),
        source_kind="document",
        source_ref_key="doc.orbit_11_launch",
    ),
    EdgeSeed(
        subject_key="person.jordan_reyes",
        predicate="manages",
        object_key="org.zephyr_data",
        fact="Jordan Reyes is our champion at Zephyr.",
        valid_from=_dt(2025, 9, 1),
        confidence=0.9,
        source_kind="document",
        source_ref_key="doc.postmortem_zephyr",
    ),
    # ---------- Projects ----------
    EdgeSeed(
        subject_key="project.orbit",
        predicate="related_to",
        object_key="org.halcyon",
        fact="Orbit is Halcyon Labs' flagship product.",
        valid_from=_dt(2025, 1, 6),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="project.orbit_scout",
        predicate="part_of",
        object_key="project.orbit",
        fact="Orbit Scout is the free tier of Orbit.",
        valid_from=_dt(2025, 11, 19),
        source_kind="manual",
    ),
    EdgeSeed(
        subject_key="project.prism",
        predicate="part_of",
        object_key="project.orbit",
        fact="Project Prism is the Q1 2026 re-architecture of Orbit storage.",
        valid_from=_dt(2026, 1, 13),
        source_kind="document",
        source_ref_key="doc.strategy_memo_2026",
    ),
    EdgeSeed(
        subject_key="person.alex_park",
        predicate="works_on",
        object_key="project.prism",
        fact="Alex Park leads Project Prism.",
        valid_from=_dt(2026, 1, 13),
        source_kind="document",
        source_ref_key="doc.strategy_memo_2026",
    ),
    EdgeSeed(
        subject_key="person.elena_kowalczyk",
        predicate="works_on",
        object_key="project.prism",
        fact="Elena Kowalczyk staffed on Project Prism.",
        valid_from=_dt(2026, 1, 20),
        source_kind="document",
        source_ref_key="doc.strategy_memo_2026",
    ),
    EdgeSeed(
        subject_key="person.elena_kowalczyk",
        predicate="works_on",
        object_key="project.orbit",
        fact="Elena Kowalczyk delivered the Orbit 1.1 eval fixes.",
        valid_from=_dt(2025, 10, 20),
        valid_to=_dt(2026, 1, 20),
        source_kind="document",
        source_ref_key="doc.orbit_11_launch",
    ),
    EdgeSeed(
        subject_key="person.sarah_chen",
        predicate="works_on",
        object_key="project.hiring_2026_q1",
        fact="Sarah leads the Q1 2026 hiring push.",
        valid_from=_dt(2026, 1, 15),
        source_kind="document",
        source_ref_key="doc.hiring_plan_2026",
    ),
    # ---------- Document authorship ----------
    EdgeSeed(
        subject_key="person.sarah_chen",
        predicate="authored",
        object_key="doc.strategy_memo_2026",
        fact="Sarah authored the 2026 strategy memo.",
        valid_from=_dt(2026, 1, 12),
        source_kind="document",
        source_ref_key="doc.strategy_memo_2026",
    ),
    EdgeSeed(
        subject_key="person.alex_park",
        predicate="authored",
        object_key="doc.postmortem_zephyr",
        fact="Alex wrote the Zephyr pilot postmortem.",
        valid_from=_dt(2025, 10, 16),
        source_kind="document",
        source_ref_key="doc.postmortem_zephyr",
    ),
    EdgeSeed(
        subject_key="person.elena_kowalczyk",
        predicate="authored",
        object_key="doc.orbit_11_launch",
        fact="Elena wrote the Orbit 1.1 launch notes.",
        valid_from=_dt(2025, 11, 18),
        source_kind="document",
        source_ref_key="doc.orbit_11_launch",
    ),
    EdgeSeed(
        subject_key="person.sarah_chen",
        predicate="authored",
        object_key="doc.hiring_plan_2026",
        fact="Sarah drafted the 2026 Q1 hiring plan.",
        valid_from=_dt(2026, 1, 15),
        source_kind="document",
        source_ref_key="doc.hiring_plan_2026",
    ),
    # ---------- Platform partner ----------
    EdgeSeed(
        subject_key="org.halcyon",
        predicate="member_of",
        object_key="org.dynamiq_canonical",
        fact="Halcyon uses Dynamiq Context Engine as Orbit's memory layer.",
        valid_from=_dt(2025, 6, 1),
        confidence=0.9,
        source_kind="manual",
    ),
)
