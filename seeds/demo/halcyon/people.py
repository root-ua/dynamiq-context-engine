"""People in the Halcyon Labs narrative.

Kept short on purpose: a dense, well-chosen cast reads more real than a
long random list. Every person here is referenced by at least one edge
and at least one document.

Aliases cover the plausible shapes you'd see in a real workspace:
  - Short form ("Sarah")
  - Initials ("S. Chen")
  - Slack handle ("@sarah")

`props` carries role/email/location/joined_date. Props flow into
entity.props and are visible on the entity detail page.
"""

from seeds.demo.halcyon._types import EntitySeed

PEOPLE: tuple[EntitySeed, ...] = (
    EntitySeed(
        key="person.sarah_chen",
        type_slug="person",
        canonical="Sarah Chen",
        aliases=("Sarah", "S. Chen", "@sarah"),
        summary=(
            "Co-founder and CEO of Halcyon Labs. Previously led product at "
            "Anthropic, earlier staff PM at Stripe. Based in San Francisco. "
            "Drives fundraising, customer relationships, and long-range "
            "strategy."
        ),
        props={
            "role": "CEO",
            "email": "sarah@halcyonlabs.com",
            "location": "San Francisco, CA",
            "timezone": "America/Los_Angeles",
            "joined_at": "2025-01-06",
            "linkedin": "linkedin.com/in/sarahchen-demo",
        },
    ),
    EntitySeed(
        key="person.alex_park",
        type_slug="person",
        canonical="Alex Park",
        aliases=("Alex", "@alex", "A. Park", "Park"),
        summary=(
            "Co-founder and CTO. Started as Founding Engineer (Jan-Jul 2025) "
            "then promoted to Head of Engineering. Previously staff engineer "
            "on Meta's PyTorch training infra team. Owns core platform + "
            "eval harness."
        ),
        props={
            "role": "Head of Engineering",
            "email": "alex@halcyonlabs.com",
            "location": "San Francisco, CA",
            "timezone": "America/Los_Angeles",
            "joined_at": "2025-01-06",
            "github": "github.com/apark-demo",
        },
    ),
    EntitySeed(
        key="person.priya_raghavan",
        type_slug="person",
        canonical="Priya Raghavan",
        aliases=("Priya", "Priya R.", "@priya"),
        summary=(
            "Founding designer. Joined February 2025 from Linear. Owns the "
            "full UX surface — product, marketing, docs. Remote from "
            "Bangalore; runs a 5-day-week schedule anchored against PT."
        ),
        props={
            "role": "Founding Designer",
            "email": "priya@halcyonlabs.com",
            "location": "Bangalore, India",
            "timezone": "Asia/Kolkata",
            "joined_at": "2025-02-17",
        },
    ),
    EntitySeed(
        key="person.marcus_webb",
        type_slug="person",
        canonical="Marcus Webb",
        aliases=("Marcus", "@mw", "M. Webb"),
        summary=(
            "First AE. Hired August 2025 from DataDog's mid-market team. "
            "Owns the top-of-funnel + late-stage motion for mid-market "
            "accounts. Zephyr Data is his first closed deal."
        ),
        props={
            "role": "Account Executive",
            "email": "marcus@halcyonlabs.com",
            "location": "New York, NY",
            "timezone": "America/New_York",
            "joined_at": "2025-08-04",
        },
    ),
    EntitySeed(
        key="person.elena_kowalczyk",
        type_slug="person",
        canonical="Elena Kowalczyk",
        aliases=("Elena", "@elena", "E.K."),
        summary=(
            "Third engineering hire. Joined August 2025 from a Berlin-based "
            "ML-ops startup. Owns the ingestion + projection pipeline and "
            "wrote most of Orbit 1.1's eval-accuracy fixes."
        ),
        props={
            "role": "Senior Engineer",
            "email": "elena@halcyonlabs.com",
            "location": "Warsaw, Poland",
            "timezone": "Europe/Warsaw",
            "joined_at": "2025-08-18",
        },
    ),
    EntitySeed(
        key="person.jordan_reyes",
        type_slug="person",
        canonical="Jordan Reyes",
        aliases=("Jordan", "@jreyes", "J. Reyes"),
        summary=(
            "Staff engineer at Zephyr Data. Owned the Orbit pilot on their "
            "side. Was the one who caught the eval-accuracy issue that "
            "pulled the LOI in October 2025; championed the re-signing in "
            "November after the fix shipped."
        ),
        props={
            "role": "Staff Engineer",
            "email": "jordan@zephyrdata.io",
            "employer_key": "org.zephyr_data",
            "location": "Austin, TX",
            "timezone": "America/Chicago",
        },
    ),
    EntitySeed(
        key="person.mira_okonkwo",
        type_slug="person",
        canonical="Mira Okonkwo",
        aliases=("Mira", "M. Okonkwo"),
        summary=(
            "Partner at Atlas Ventures. Led the Halcyon seed. Board observer "
            "through Series A. Background in infra — ex-VMware, then early "
            "Snowflake."
        ),
        props={
            "role": "Partner",
            "email": "mira@atlas.vc",
            "employer_key": "org.atlas_ventures",
            "location": "Menlo Park, CA",
            "timezone": "America/Los_Angeles",
        },
    ),
    EntitySeed(
        key="person.hana_lindqvist",
        type_slug="person",
        canonical="Hana Lindqvist",
        aliases=("Hana", "H. Lindqvist"),
        summary=(
            "Partner at Glass Ridge Capital. Led the Halcyon Series A in "
            "February 2026. Focuses on developer tools; previously invested "
            "in Tailscale and Grafana."
        ),
        props={
            "role": "Partner",
            "email": "hana@glassridge.com",
            "employer_key": "org.glass_ridge",
            "location": "Stockholm, Sweden",
            "timezone": "Europe/Stockholm",
        },
    ),
)
