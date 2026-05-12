"""Organizations: Halcyon itself, investors, customers, a competitor."""

from seeds.demo.halcyon._types import EntitySeed

ORGS: tuple[EntitySeed, ...] = (
    EntitySeed(
        key="org.halcyon",
        type_slug="organization",
        canonical="Halcyon Labs",
        aliases=("Halcyon", "Halcyon, Inc."),
        summary=(
            "AI reliability tooling. Telemetry, evals, and production guard "
            "rails for teams shipping LLM agents. Seed 2025 (Atlas Ventures), "
            "Series A 2026 (Glass Ridge). Headquartered in San Francisco; "
            "8 people as of Feb 2026."
        ),
        props={
            "founded_at": "2025-01-06",
            "headquarters": "San Francisco, CA",
            "stage": "Series A",
            "headcount": 8,
            "website": "https://halcyonlabs.com",
        },
    ),
    EntitySeed(
        key="org.atlas_ventures",
        type_slug="organization",
        canonical="Atlas Ventures",
        aliases=("Atlas", "Atlas VC"),
        summary=(
            "Early-stage enterprise / infra VC. Led Halcyon's seed (Mar "
            "2025). Mira Okonkwo sits on our board as observer."
        ),
        props={
            "kind": "investor",
            "website": "https://atlas.vc",
            "stage_focus": "seed_to_series_a",
        },
    ),
    EntitySeed(
        key="org.glass_ridge",
        type_slug="organization",
        canonical="Glass Ridge Capital",
        aliases=("Glass Ridge",),
        summary=(
            "Developer-tools focused Series A/B fund out of Stockholm. Led "
            "our Series A in Feb 2026 ($15M). Portfolio includes Tailscale, "
            "Grafana, Fly.io."
        ),
        props={
            "kind": "investor",
            "website": "https://glassridge.com",
            "stage_focus": "series_a_to_b",
        },
    ),
    EntitySeed(
        key="org.zephyr_data",
        type_slug="organization",
        canonical="Zephyr Data",
        aliases=("Zephyr",),
        summary=(
            "Real-time ML feature-store startup. First Halcyon customer. "
            "Signed LOI Sep 2025, pulled it Oct 2025 after a serious eval "
            "accuracy issue with Orbit's agent evaluator. Re-signed a 1-year "
            "contract Nov 2025 after Orbit 1.1 shipped the fix. Jordan "
            "Reyes is our champion."
        ),
        props={
            "kind": "customer",
            "tier": "mid_market",
            "contract_value_usd": 84000,
            "contract_start": "2025-11-19",
            "website": "https://zephyrdata.io",
        },
    ),
    EntitySeed(
        key="org.orbital_systems",
        type_slug="organization",
        canonical="Orbital Systems",
        aliases=("Orbital",),
        summary=(
            "Direct competitor. YC W24 company, raised a $6M seed in early "
            "2025. Stronger on the eval side; weaker on the telemetry + "
            "traces surface. Targets the same mid-market-AI-platform ICP "
            "we do."
        ),
        props={
            "kind": "competitor",
            "stage": "seed",
            "website": "https://orbital.systems",
        },
    ),
    # The merge-case pair: "Dynamiq" and "Dynamiq AI" referred to the same
    # entity; the platform should show them merged (survivor = first).
    EntitySeed(
        key="org.dynamiq_canonical",
        type_slug="organization",
        canonical="Dynamiq",
        aliases=("Dynamiq AI", "@dynamiq"),
        summary=(
            "Parent company. We use their Context Engine as the memory "
            "layer behind Orbit's long-running agent sessions."
        ),
        props={
            "kind": "platform_partner",
            "website": "https://getdynamiq.ai",
        },
    ),
    # Duplicate that will be merged at seed time into org.dynamiq_canonical.
    # Kept in the dataset on purpose so merge behaviour has a real example.
    EntitySeed(
        key="org.dynamiq_duplicate",
        type_slug="organization",
        canonical="Dynamiq AI",
        aliases=(),
        summary=(
            "Early variant reference to Dynamiq. Merged into 'Dynamiq' "
            "(canonical). Kept as a pointer; do not edit."
        ),
        props={"kind": "platform_partner"},
    ),
)
