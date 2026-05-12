"""Workspace-scoped additions to the built-in ontology.

The built-in schema already has `person`, `organization`, `project`,
`task`, `meeting`, `document`, `note`, `topic`, plus a handful of
relations. The Halcyon story needs a couple of specifics the built-ins
don't cover — a `deal` entity type for customer contracts, and a
`funded_by` relation for investor rounds.

Keeping these narrow on purpose: they're demo-workspace-only. A real user
who wants to add their own should do it via the ontology editor in the UI.
"""

from seeds.demo.halcyon._types import EntityTypeSeed, RelationTypeSeed

EXTRA_ENTITY_TYPES: tuple[EntityTypeSeed, ...] = (
    EntityTypeSeed(
        slug="deal",
        name="Deal",
        extends="work",
        description=(
            "A customer contract or its precursor (LOI, pilot, renewal). "
            "Tracks counterparty, stage, ACV, and lifecycle timestamps."
        ),
        schema={
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["loi", "pilot", "active", "renewed", "churned"],
                },
                "acv_usd": {"type": "number"},
                "counterparty": {"type": "string"},
                "signed_at": {"type": "string", "format": "date"},
                "closed_at": {"type": "string", "format": "date"},
                "owner": {"type": "string"},
            },
            "required": ["stage"],
            "additionalProperties": True,
        },
        ui_hints={"icon": "handshake", "color": "emerald"},
    ),
)

EXTRA_RELATION_TYPES: tuple[RelationTypeSeed, ...] = (
    RelationTypeSeed(
        slug="funded_by",
        name="Funded by",
        description=(
            "A funding round relationship. Subject is the company raising; "
            "object is the investor. Props carry round type + amount."
        ),
        domain="organization",
        range_="organization",
        temporal=True,
    ),
    RelationTypeSeed(
        slug="customer_of",
        name="Customer of",
        description=(
            "Subject (customer org) is a paying customer of the object "
            "(vendor org). Temporal: contract has a start/end."
        ),
        domain="organization",
        range_="organization",
        temporal=True,
    ),
    RelationTypeSeed(
        slug="works_on",
        name="Works on",
        description=(
            "Person is actively staffed on a project. Temporal — people "
            "rotate between projects."
        ),
        domain="person",
        range_="project",
        temporal=True,
    ),
)
