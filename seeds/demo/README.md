# Demo dataset

The [`halcyon/`](halcyon/) directory holds the hand-authored demo data —
a fictional AI-reliability-tooling startup called **Halcyon Labs** across
a 14-month timeline. Every Dynamiq feature (graph, bi-temporal edges,
contradictions, documents with @mentions, episodes, agent sessions, an
extended ontology) has at least one example in the dataset.

## Seeding a workspace

**From the UI**: sign up, and on the onboarding screen check *Also create
a demo workspace*. A `Demo — Halcyon Labs` workspace appears in the
switcher alongside your real one.

**From the CLI** (inside the backend container):

```bash
# Create a new demo workspace owned by an existing user:
python -m app.scripts.seed_demo create --owner-email me@example.com

# Populate an existing empty workspace:
python -m app.scripts.seed_demo populate --workspace-id <uuid>

# Wipe + reseed (dev only):
python -m app.scripts.seed_demo reset --workspace-slug demo-halcyon-abc
```

**From the REST API** (authenticated as a workspace owner/admin):

```bash
curl -X POST https://<api>/api/workspaces/<id>/seed-demo \
  -H "Authorization: Bearer <token>"
```

## Editing the dataset

See [`halcyon/narrative.md`](halcyon/narrative.md) — the authorial
reference. The timeline there should stay consistent with the data
modules. When you add a new person, org, edge, or document:

1. Add the entry to the appropriate module (`people.py`, `orgs.py`, etc.).
2. Reference it by `key` from `relationships.py` or `documents.py`.
3. Update the narrative.md timeline if you introduce a new date.

Editing rules:

- **Keys are forever**: every `EntitySeed.key`, `DocumentSeed.key`, etc.
  is a dedupe handle. The seeder uses them to make re-runs idempotent.
  Renaming a key means existing seeded workspaces won't match the new
  entry and you'll get duplicates.
- **No randomness**: the dataset is hand-authored on purpose. If you're
  tempted to reach for Faker, author one more entry by hand — realism
  comes from the prose, not the volume.
- **Respect the ontology**: `type_slug` must match either a built-in
  (see `seeds/ontology.yaml`) or one of the workspace-scoped additions
  declared in `ontology_additions.py`.
