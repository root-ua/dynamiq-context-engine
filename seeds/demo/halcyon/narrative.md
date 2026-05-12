# Halcyon Labs — narrative reference

Authorial reference for the demo dataset. Edit the data modules alongside
this doc so the timeline stays coherent.

## The company

**Halcyon Labs** is a fictional AI-reliability-tooling startup. Founded Jan 2025.
Their product, **Orbit**, is a telemetry + eval harness for teams shipping LLM
agents to production.

## Timeline

| Date | Event |
|---|---|
| 2025-01-06 | Founded by Sarah Chen (CEO) and Alex Park (Founding Engineer). |
| 2025-02-17 | Priya Raghavan joins as founding designer. |
| 2025-03-10 | Seed round: $4M from Atlas Ventures (Mira Okonkwo). |
| 2025-04-22 | Orbit alpha launches. |
| 2025-05-06 | Project Lumen (browser-extension exploration) kicks off. |
| 2025-05-14 | Project Lumen shelved. |
| 2025-06-01 | Halcyon starts using Dynamiq Context Engine for Orbit's memory layer. |
| 2025-07-14 | Alex Park promoted from Founding Engineer → Head of Engineering. |
| 2025-08-04 | Marcus Webb joins as first AE. |
| 2025-08-18 | Elena Kowalczyk joins as 3rd engineer. |
| 2025-09-23 | Zephyr Data signs LOI for pilot. |
| 2025-10-02 | Jordan Reyes @ Zephyr files eval-accuracy ticket. |
| 2025-10-06 | Founders sync identifies the root cause (sampler seeding bug). |
| 2025-10-10 | Alex flies to Austin to meet Zephyr in person. |
| 2025-10-12 | Orbit 1.0.3 ships with deterministic seeding. |
| 2025-10-14 | Zephyr withdraws LOI. |
| 2025-10-16 | Alex writes the postmortem. |
| 2025-11-18 | Orbit 1.1 ships (Elena leads). Audit manifests + Orbit Scout GA. |
| 2025-11-19 | Zephyr countersigns 1-year contract ($84K ACV). |
| 2025-12-02 | Agent session: Claude Code asks about Zephyr + makes add_fact. |
| 2025-12-15 | We start telling people we're targeting $20M Series A. |
| 2026-01-12 | Sarah writes the 2026 strategy memo. |
| 2026-01-13 | Project Prism kicks off. |
| 2026-01-14 | Agent session: Cursor scopes Prism from memory. |
| 2026-01-15 | Sarah publishes the Q1 hiring plan. |
| 2026-02-06 | Series A closes at $15M (led by Glass Ridge), not $20M. |

## Key people (9)

- **Sarah Chen** — CEO, co-founder. Ex-Anthropic PM. SF.
- **Alex Park** — CTO, co-founder. Ex-Meta staff eng. SF. Korean-American.
- **Priya Raghavan** — Founding designer. Ex-Linear. Bangalore (remote).
- **Marcus Webb** — First AE. Ex-Datadog. NYC.
- **Elena Kowalczyk** — Senior engineer. Ex-Berlin ML-ops startup. Warsaw.
- **Jordan Reyes** — Our customer champion at Zephyr. Austin.
- **Mira Okonkwo** — Partner, Atlas Ventures (seed lead). Menlo Park.
- **Hana Lindqvist** — Partner, Glass Ridge Capital (Series A lead). Stockholm.

## Organizations (7)

- **Halcyon Labs** — us.
- **Atlas Ventures** — seed investor.
- **Glass Ridge Capital** — Series A lead.
- **Zephyr Data** — first paying customer.
- **Orbital Systems** — competitor.
- **Dynamiq** (canonical) + **Dynamiq AI** (merged-into-canonical duplicate).

## Projects (5)

- **Orbit** — flagship product.
- **Orbit Scout** — free tier, launched Nov 2025.
- **Project Prism** — Q1 2026 re-architecture. In progress.
- **2026 Q1 Hiring** — hiring project.
- **Project Lumen** — deprecated side exploration. Soft-deleted.

## Documents (4)

- **2026 strategy memo** (Sarah, Jan 12 2026)
- **Zephyr pilot postmortem** (Alex, Oct 16 2025)
- **Orbit 1.1 launch notes** (Elena, Nov 18 2025)
- **2026 Q1 hiring plan** (Sarah, Jan 15 2026)

## Episodes (2)

- Founders-sync Zoom transcript, Oct 6 2025 (where the Zephyr bug is identified).
- Slack export from Nov 19 2025 (celebrating Zephyr re-signing).

## Agent sessions (2)

- Claude Code session Dec 2 2025: investigating Zephyr context, making
  an `add_fact` call about Jordan agreeing to reference calls.
- Cursor session Jan 14 2026: scoping Prism from memory.

## Feature-demonstration matrix

Every product feature should be reachable from the seeded data:

| Feature | Demonstrated by |
|---|---|
| @mentions resolving | Any document — e.g. `2026 strategy memo` mentions Sarah, Alex, Prism, Atlas. |
| Graph clusters | Halcyon + its people + its projects form a tight cluster; investors + customer are peripheral. |
| Bi-temporal edges | Alex Park's role history: Founding Engineer (Jan–Jul 2025) → Head of Eng (Jul 2025 →). |
| Contradictions | $20M Series A target invalidated when the $15M actual closed. Zephyr LOI invalidated, replaced with contract. |
| Entity merges | `Dynamiq AI` merged into `Dynamiq`. |
| Low-confidence facts | Internal codename edge for Prism: confidence 0.9. Agent-sourced $20M target: confidence 0.7. |
| Soft-deleted entity | `Project Lumen`. |
| Ontology additions | `deal` entity type, `funded_by` + `customer_of` + `works_on` relations. |
| Documents | 4 documents, each >200 words, realistic voice. |
| Backlinks | `person.jordan_reyes` is mentioned in both `doc.postmortem_zephyr` and `doc.orbit_11_launch`. |
| Episodes + extraction | 2 episodes with pre-populated extracted refs. |
| Agent console | 2 sessions with 4 + 3 tool calls. |
| Search | `"Series A"` hits memo + funding edge + episode. `"Jordan"` hits entity + postmortem + launch notes + agent session. |

## Writing rules (for future edits)

- No Alice/Bob names. Use the cast above.
- No "Example Corp", "Acme". Use the org list above.
- All dates in the narrative above. Don't invent new years; stay in 2024–2026.
- Documents should read like real internal docs — specific details,
  technical claims that are coherent (don't mix AI and blockchain
  unless it's ironic and the irony is obvious).
- Contradictions should have a plausible reason attached
  (`invalidate_reason`). "We learned Y contradicts X" is the shape.
