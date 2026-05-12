"""Projects and products in the Halcyon narrative.

The built-in `project` schema constrains `status` to
['planning', 'active', 'on_hold', 'completed', 'archived']
and dates to ISO dates at keys `start_date` / `end_date`. We fit into
that schema rather than inventing our own (which we could via a
workspace-scoped subtype; keeping the built-in schema keeps the
ontology editor demo simpler).
"""

from seeds.demo.halcyon._types import EntitySeed

PROJECTS: tuple[EntitySeed, ...] = (
    EntitySeed(
        key="project.orbit",
        type_slug="project",
        canonical="Orbit",
        aliases=("orbit",),
        summary=(
            "Halcyon's flagship product. Telemetry + eval harness for LLM "
            "agents in production. Alpha launched Apr 2025; 1.0 Sep 2025; "
            "1.1 (accuracy fixes) Nov 2025. Roughly 70% of engineering "
            "attention."
        ),
        props={
            "status": "active",
            "start_date": "2025-04-22",
            "latest_version": "1.1",
            "repo": "github.com/halcyon/orbit",
        },
    ),
    EntitySeed(
        key="project.orbit_scout",
        type_slug="project",
        canonical="Orbit Scout",
        aliases=("Scout",),
        summary=(
            "Free tier of Orbit. Lower limits, self-serve signup. Launched "
            "Nov 2025 to seed a top-of-funnel pipeline and lower the "
            "friction for design-partner conversion."
        ),
        props={
            "status": "active",
            "start_date": "2025-11-19",
            "parent_project_key": "project.orbit",
        },
    ),
    EntitySeed(
        key="project.prism",
        type_slug="project",
        canonical="Project Prism",
        aliases=("Prism",),
        summary=(
            "Internal codename for the Q1 2026 multi-tenant re-architecture "
            "of Orbit's storage layer. Target: 10x our current trace "
            "ingestion throughput and drop per-tenant query P99 from 1.8s "
            "to <300ms. Kicked off Jan 2026."
        ),
        props={
            "status": "active",
            "start_date": "2026-01-13",
            "end_date": "2026-04-30",
            "lead_person_key": "person.alex_park",
            "parent_project_key": "project.orbit",
        },
    ),
    EntitySeed(
        key="project.hiring_2026_q1",
        type_slug="project",
        canonical="2026 Q1 Hiring",
        aliases=("Hiring Q1 2026",),
        summary=(
            "Bring the team from 8 → 12 by end of Q1 2026. Priorities: "
            "senior backend eng (2), forward-deployed eng (1), first head "
            "of GTM (1). Drives recruiter contract + interview loop revamp."
        ),
        props={
            "status": "active",
            "start_date": "2026-01-15",
            "end_date": "2026-03-31",
            "lead_person_key": "person.sarah_chen",
        },
    ),
    # A soft-deleted project. Gives us a real example of the "deleted" state
    # without breaking referential integrity (no edges point at it after
    # the deletion, but it exists in the entity table as deleted_at IS NOT NULL).
    EntitySeed(
        key="project.lumen_deprecated",
        type_slug="project",
        canonical="Project Lumen (deprecated)",
        aliases=(),
        summary=(
            "Short-lived exploration of a browser-extension surface for "
            "Orbit. Shelved in May 2025 after a week of prototyping — "
            "kept as a record, soft-deleted."
        ),
        props={
            "status": "archived",
            "start_date": "2025-05-06",
            "end_date": "2025-05-14",
        },
    ),
)
