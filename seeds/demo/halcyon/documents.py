"""Documents in the Halcyon workspace.

Four hand-authored documents that read like real internal content:

1. Founders' 2026 strategy memo (Sarah, Jan 12 2026)
2. Zephyr pilot postmortem (Alex, Oct 16 2025)
3. Orbit 1.1 launch notes (Elena, Nov 18 2025)
4. 2026 Q1 hiring plan (Sarah, Jan 15 2026)

Each uses inline `@mention` entity references so the graph backlinks
are populated naturally. Content is >200 words and is internally
coherent — reader should recognise the shape of a real working doc.
"""

from datetime import UTC, datetime

from seeds.demo.halcyon._block_helpers import (
    Bullet,
    Code,
    H1,
    H2,
    H3,
    Link,
    M,
    Numbered,
    P,
    Quote,
    T,
    finalize,
)
from seeds.demo.halcyon._types import DocumentSeed


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


_STRATEGY_MEMO_BLOCKS = finalize([
    H1(T("2026 strategy memo")),
    P(
        T("Draft — ", italic=True),
        T("will revise before the Feb 10 board meeting.", italic=True),
    ),
    H2(T("Where we are")),
    P(
        T("We closed our $15M Series A with "),
        M("org.glass_ridge"),
        T(" on Feb 6. Runway through Q2 2028. Team of 8, all-remote with an "
          "SF hub. "),
        M("person.alex_park"),
        T(" stepped into Head of Eng in July; "),
        M("person.elena_kowalczyk"),
        T(" joined shortly after and has owned the ingestion pipeline since."),
    ),
    P(
        T("Revenue: one paid contract ("),
        M("org.zephyr_data"),
        T(", $84K ACV) and ~40 "),
        M("project.orbit_scout"),
        T(" active accounts converting at 3.2%. Pipeline is thin but we have "
          "conviction on the Zephyr-shaped ICP (real-time ML infra teams)."),
    ),
    H2(T("Where we're going")),
    H3(T("Ship ", ), M("project.prism"), T(" by end of April")),
    P(
        T("The single biggest thing blocking our mid-market push is Orbit's "
          "per-tenant P99. We're at 1.8s on the ingestion path; we need "
          "sub-300ms. "),
        M("project.prism"),
        T(" is the re-architecture. "),
        M("person.alex_park"),
        T(" is driving; "),
        M("person.elena_kowalczyk"),
        T(" is the #2. Target ship April 30. Board milestone."),
    ),
    H3(T("Bring headcount to 12")),
    P(
        T("See the "),
        M("project.hiring_2026_q1", label="Q1 hiring plan"),
        T(" for the funnel view. Short version: 2 senior backend, 1 forward "
          "deployed, 1 first head of GTM. "),
        M("person.marcus_webb"),
        T(" continues to own AE motion; the GTM hire is a step up."),
    ),
    H3(T("10 design partners by end of Q2")),
    P(
        T("Priority segments (unchanged from Q4): real-time ML platforms, "
          "internal-agents teams at mid-size tech cos, and the infra-eng "
          "wing of a handful of late-stage startups. "),
        M("org.zephyr_data"),
        T(" is the reference. "),
        M("person.marcus_webb"),
        T(" to own the pipeline; "),
        M("person.sarah_chen"),
        T(" on every first exec call."),
    ),
    H2(T("Risks")),
    Bullet(
        T("We're betting that "),
        M("org.orbital_systems"),
        T(" stays stuck on the eval-only wedge. If they expand into "
          "production telemetry (signals suggest Q3), the market gets "
          "noisier. Mitigation: ship Prism + get 5 named-brand refs."),
    ),
    Bullet(
        T("Our platform-partner dependency on "),
        M("org.dynamiq_canonical"),
        T(" is deeper than I'd like. If their pricing changes, we re-spec. "
          "Talking to "),
        M("person.mira_okonkwo"),
        T(" about a fallback before Q2."),
    ),
    Bullet(
        T("Key-person risk on "),
        M("person.alex_park"),
        T(". We need the Prism docs good enough that "),
        M("person.elena_kowalczyk"),
        T(" could ship a v1 without him. Action item for Alex this month."),
    ),
    H2(T("Funding posture")),
    P(
        T("We are not raising in 2026. Any inbound from "),
        M("org.glass_ridge"),
        T("-adjacent funds or from "),
        M("person.mira_okonkwo"),
        T("'s network — take the meeting, stay responsive, don't commit. "
          "We have leverage for the next round."),
    ),
    Quote(
        T("— Sarah, Jan 12 2026"),
    ),
])


_POSTMORTEM_BLOCKS = finalize([
    H1(T("Zephyr pilot postmortem")),
    P(
        T("Status: ", bold=True),
        T("LOI withdrawn Oct 14. Pilot on pause. Owners: "),
        M("person.alex_park"),
        T(" (eng), "),
        M("person.marcus_webb"),
        T(" (account)."),
    ),
    H2(T("What happened")),
    P(
        T("On Oct 2, "),
        M("person.jordan_reyes"),
        T(" filed a ticket showing Orbit's agent-eval score disagreed with "
          "his human-labelled golden set on 17% of samples. We'd told the "
          "pilot team we were at <4% disagreement. He re-ran with 3 seeds; "
          "the spread was consistent."),
    ),
    P(
        T("Oct 3–9 we tried to reproduce. Turns out the sampler in the eval "
          "runner was seeded off wall-clock time, not off the run id. Two "
          "'identical' runs diverged on any prompt where the LLM saw "
          "borderline content. On Zephyr's traffic (ML feature-store "
          "pipelines, lots of numeric-reasoning prompts) the issue "
          "amplified."),
    ),
    P(
        T("Oct 10 I flew to Austin. Met with "),
        M("person.jordan_reyes"),
        T(" and their ML infra lead. Showed the root cause, shared the fix "
          "branch. They appreciated it but said we'd broken trust and their "
          "Security team wasn't going to re-sign without a full audit trail. "
          "Oct 14 they formally pulled the LOI."),
    ),
    H2(T("What we fixed")),
    Numbered(
        T("Deterministic seeding: run id → SHA-256 → numpy seed. Shipped "),
        T("in Orbit 1.0.3 ", bold=True),
        T("(Oct 12)."),
    ),
    Numbered(
        T("Reproducibility test: every PR to the eval runner now runs a "
          "10-seed spread; CI fails if any two seeds disagree on the "
          "golden set."),
    ),
    Numbered(
        T("Audit trail: every eval run emits a signed manifest (run id, "
          "seed, model ident, git sha, prompt hash) to the customer's "
          "S3 bucket. Shipped in "),
        T("1.1", bold=True),
        T("."),
    ),
    H2(T("What we learned")),
    Bullet(
        T("We had a claim ('<4% disagreement') in the pilot deck that "
          "nobody could actually reproduce under test. Don't ship "
          "customer-facing numbers without a reproducibility gate."),
    ),
    Bullet(
        T("Customer trust breaks fast and rebuilds slow. Our best shot "
          "at a renewal was to show up in person with the fix already "
          "written. Good instinct, worth the flight."),
    ),
    Bullet(
        T("The sampler bug was 6 lines and two years old — it pre-dates "
          "Halcyon. We inherited it from "),
        M("person.alex_park"),
        T("'s old PyTorch-eval side project. Review old code you import "
          "the way you'd review a new dep."),
    ),
    H2(T("Follow-ups")),
    Bullet(T("Get the re-sign. ("), M("person.marcus_webb"), T(", by Nov 15)")),
    Bullet(T("Audit every 'ship' claim in the pricing page. ("),
           M("person.sarah_chen"), T(", by Oct 31)")),
    Bullet(T("Reproducibility harness as a customer-facing feature. ("),
           M("person.alex_park"), T(", Orbit 1.2)")),
    Quote(T("— Alex, Oct 16 2025")),
])


_ORBIT_11_LAUNCH_BLOCKS = finalize([
    H1(T("Orbit 1.1 — launch notes")),
    P(
        T("Ship date: Nov 18, 2025. Ship-owner: "),
        M("person.elena_kowalczyk"),
        T(". QA sign-off: "),
        M("person.alex_park"),
        T("."),
    ),
    H2(T("Headline changes")),
    Bullet(
        T("Deterministic eval seeding (carries the 1.0.3 hotfix forward, "
          "now canonical)."),
    ),
    Bullet(
        T("Signed audit manifests on every eval run. See "),
        M("doc.postmortem_zephyr"),
        T(" for background."),
    ),
    Bullet(
        T("Orbit Scout tier GA. Self-serve signup, 100K traces/month free, "
          "auto-upgrade flow to paid when you cross the limit."),
    ),
    Bullet(
        T("gRPC ingestion (experimental, behind a flag). ~3x throughput on "
          "our internal load generator vs. the HTTP path."),
    ),
    H2(T("Customer call-out")),
    P(
        T("Special thanks to "),
        M("person.jordan_reyes"),
        T(" at "),
        M("org.zephyr_data"),
        T(". His reproducibility bug report is the reason the manifest "
          "feature exists. Zephyr re-signed on Nov 19 — one-year contract, "
          "1.1 is their production rev."),
    ),
    H2(T("Migration")),
    P(T("If you're coming from 1.0.x:")),
    Numbered(T("Update your SDK to >= 1.1.0.")),
    Numbered(T("If you set OB_EVAL_SEED in your CI, remove it — we seed "
              "deterministically off run id now. Leaving it in is harmless "
              "but emits a deprecation warning.")),
    Numbered(T("Audit manifests go to the S3 bucket named in your org "
              "settings. If you haven't set one, we fall back to "
              "ob-audit-{org-slug} in us-east-1.")),
    H3(T("Example")),
    Code(
        "from orbit import Client\n"
        "client = Client(api_key=os.environ['ORBIT_KEY'])\n"
        "run = client.eval.run(\n"
        "    dataset='golden-v3',\n"
        "    model='claude-sonnet-4-6',\n"
        ")\n"
        "print(run.manifest_url)  # signed audit manifest in S3",
        language="python",
    ),
    H2(T("What's next (1.2)")),
    Bullet(T("Customer-visible reproducibility dashboard")),
    Bullet(T("Multi-tenant query perf work (precursor to "),
           M("project.prism"), T(")")),
    Bullet(T("OTEL export for traces")),
    Quote(T("— Elena, Nov 18 2025")),
])


_HIRING_PLAN_BLOCKS = finalize([
    H1(T("2026 Q1 hiring plan")),
    P(
        T("Owner: "),
        M("person.sarah_chen"),
        T(". Recruiter contract: Ascend Talent (renewed through June)."),
    ),
    H2(T("What we're hiring for")),
    Numbered(
        T("Senior backend engineer — data pipeline. Leads Prism after "
          "Alex hands off. 2 hires."),
    ),
    Numbered(
        T("Forward-deployed engineer. Customer-facing, 50/50 code/call. "
          "Marcus needs the cover on mid-market. 1 hire."),
    ),
    Numbered(
        T("First head of GTM. Step up from AE. Owns expand, upmarket, and "
          "the top of the funnel from inbound. 1 hire."),
    ),
    H2(T("Pipeline")),
    Bullet(T("Backend #1: 4 candidates in phone screen. 2 from "),
           M("person.alex_park"), T("'s network, 2 from Ascend. "
           "Target offer by end of February.")),
    Bullet(T("Backend #2: 1 strong candidate ("),
           T("ex-Databricks", italic=True),
           T(") scheduled for on-site week of Feb 17.")),
    Bullet(T("Forward-deployed: sourcing only. No solid candidates yet. "
             "Opening a dedicated search with Ascend Feb 1.")),
    Bullet(T("Head of GTM: 3 intros so far from "),
           M("person.mira_okonkwo"), T(" and "),
           M("person.hana_lindqvist"),
           T(". Two are non-starters (too senior, too junior). One live.")),
    H2(T("Interview loop")),
    P(T("We're rewriting the loop based on what didn't work hiring Elena:")),
    Bullet(T("Drop the generic systems-design round. Add a "),
           T("50-minute 'debug this broken thing in "),
           M("project.orbit"),
           T("' round instead — it's more signal for our work and more fun "
             "for candidates.")),
    Bullet(T("Move the "), M("person.sarah_chen"), T(" culture interview "
             "earlier. Too many good offers died because the candidate "
             "got a competing offer while we were still at take-home stage.")),
    Bullet(T("Add a 30-min 'ask us anything' slot. Candidates overwhelmingly "
             "say this is what moves them from 'interested' to 'yes'.")),
    H2(T("Budget")),
    P(T("All four roles target band $180K–$240K + 0.3–1.2% equity depending "
        "on level + recency of Series A. Within the model through end of "
        "2026.")),
    Quote(T("— Sarah, Jan 15 2026. Review monthly.")),
])


DOCUMENTS: tuple[DocumentSeed, ...] = (
    DocumentSeed(
        key="doc.strategy_memo_2026",
        title="2026 strategy memo",
        type_slug="document",
        author_key="person.sarah_chen",
        occurred_at=_dt(2026, 1, 12),
        blocks=_STRATEGY_MEMO_BLOCKS,
    ),
    DocumentSeed(
        key="doc.postmortem_zephyr",
        title="Zephyr pilot postmortem",
        type_slug="document",
        author_key="person.alex_park",
        occurred_at=_dt(2025, 10, 16),
        blocks=_POSTMORTEM_BLOCKS,
    ),
    DocumentSeed(
        key="doc.orbit_11_launch",
        title="Orbit 1.1 — launch notes",
        type_slug="document",
        author_key="person.elena_kowalczyk",
        occurred_at=_dt(2025, 11, 18),
        blocks=_ORBIT_11_LAUNCH_BLOCKS,
    ),
    DocumentSeed(
        key="doc.hiring_plan_2026",
        title="2026 Q1 hiring plan",
        type_slug="document",
        author_key="person.sarah_chen",
        occurred_at=_dt(2026, 1, 15),
        blocks=_HIRING_PLAN_BLOCKS,
    ),
)

# Silence linter about unused imports that are used via the public surface.
_ = (H3, Link)
