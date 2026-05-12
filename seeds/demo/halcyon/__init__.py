"""Hand-authored demo dataset — the fictional 'Halcyon Labs' narrative.

One fictional AI-tooling startup over 14 months. The data is split across
sibling modules by concern; the seeder imports them in the right order:

    ontology_additions → people / orgs / projects → relationships →
    documents → episodes → agent_sessions

Every symbol exported from this package is a plain dataclass (see
`_types.py`). No magic, no runtime behaviour — just data. The seeder in
`backend/app/domain/demo_seeder.py` is the only module that does I/O.

Editing this dataset:
- Add a new person? Append to PEOPLE in `people.py` with a stable `key`.
- Add an edge? Append to EDGES in `relationships.py`, referencing entities
  by their `key`. The seeder resolves keys → UUIDs at insert time.
- Add a document? Append to DOCUMENTS in `documents.py`. @mentions in the
  block tree are inline `entityMention` nodes — see the existing entries
  for the shape.

Stability contract: `key` values are the dataset's identifiers. Don't
rename or reuse keys; the seeder keys IRIs off them for idempotency.
"""

from seeds.demo.halcyon.agent_sessions import AGENT_SESSIONS
from seeds.demo.halcyon.documents import DOCUMENTS
from seeds.demo.halcyon.episodes import EPISODES
from seeds.demo.halcyon.ontology_additions import (
    EXTRA_ENTITY_TYPES,
    EXTRA_RELATION_TYPES,
)
from seeds.demo.halcyon.orgs import ORGS
from seeds.demo.halcyon.people import PEOPLE
from seeds.demo.halcyon.projects import PROJECTS
from seeds.demo.halcyon.relationships import EDGES

__all__ = [
    "AGENT_SESSIONS",
    "DOCUMENTS",
    "EDGES",
    "EPISODES",
    "EXTRA_ENTITY_TYPES",
    "EXTRA_RELATION_TYPES",
    "ORGS",
    "PEOPLE",
    "PROJECTS",
]
