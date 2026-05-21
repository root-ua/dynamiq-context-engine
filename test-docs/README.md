# ACL test corpus — realistic corporate stories

10 documents framed as a small fictional company's real internal corpus.
Two ACL profiles only — `everyone` and `confidential` — chosen to make
the leak surface as obvious as possible.

**Your identity (the workspace user testing this):**
- App email: `mykhailo.buleshnyi@getdynamiq.ai`
- Domain: `getdynamiq.ai`

Under the current **strict app-email matching** mode, you should see all
`everyone` docs and **none** of the `confidential` docs.

## The corpus

| # | File | ACL | Visible to you? |
|---|------|-----|-----------------|
| 1 | `01-everyone-about-us-founding-story.md` | everyone | ✅ |
| 2 | `02-everyone-employee-directory-bob.md` | everyone | ✅ |
| 3 | `03-everyone-partnership-announcement.md` | everyone | ✅ |
| 4 | `04-everyone-engineering-blog-search.md` | everyone | ✅ |
| 5 | `05-everyone-q1-all-hands-summary.md` | everyone | ✅ |
| 6 | `06-confidential-bob-performance-review.md` | confidential | 🔒 No |
| 7 | `07-confidential-company-b-msa.md` | confidential | 🔒 No |
| 8 | `08-confidential-board-minutes-acquisition.md` | confidential | 🔒 No |
| 9 | `09-confidential-security-incident-postmortem.md` | confidential | 🔒 No |
| 10 | `10-confidential-restructuring-memo.md` | confidential | 🔒 No |

## The fictional universe

Simple naming so the entity collisions are obvious at a glance.

**Our company:** Company A
**Customers:** Company B (largest, longest-tenure), Company C
**Acquisition target:** Company D (mentioned ONLY in doc 8 — this is
the entity-existence-leak test)
**People (public):** Bob (CEO), Carol (CFO), Grace (CTO), Dave (retrieval lead)
**People (confidential only):** Eve, Frank (mentioned ONLY in doc 10
— restructuring; entity-existence-leak test)
**Other:** Marta (Company B's head of research engineering; appears in
both a public press release and a confidential contract)

## Entity-collision matrix — the real point of this corpus

This is where derived-state-leak bugs hide. The same entity appears in
both `everyone` and `confidential` docs with different facts attached.
When a user sees the entity, they must see ONLY the facts visible to
them — never a summary, embedding, or aggregate that absorbed the
confidential context.

| Entity | Where it appears | What must NOT leak |
|--------|------------------|--------------------|
| **Bob** | public: 1, 2, 3, 5 — confidential: 6, 7, 8, 10 | salary, performance review, equity refresh, board concerns about hiring/founder dependence, M&A negotiating role |
| **Carol** | public: 1, 5 — confidential: 8, 9, 10 | M&A indicative terms, restructuring authorship, incident customer notification details |
| **Grace** | public: 1, 4, 5 — confidential: 8, 9, 10 | integration-cost estimate for Company D, postmortem ownership for INC-2026-014, pre-briefed on Q2 layoffs |
| **Dave** | public: 1, 4 — confidential: 9 | his team's skipped unit test that caused INC-2026-014 |
| **Company B** | public: 1, 3, 5 — confidential: 7, 9 | contract value, year-1 ramp credit, MFN clause, cross-tenant exposure during incident |
| **Company C** | public: 1, 5 — confidential: 9 | cross-tenant exposure during incident |
| **Company D** | confidential ONLY: 8 | **entire existence** — entity must be invisible |
| **Eve** | confidential ONLY: 10 | **entire existence** — entity must be invisible |
| **Frank** | confidential ONLY: 10 | **entire existence** — entity must be invisible |
| **Marta** | public: 3 — confidential: 7 | her role as signatory on Company B's MSA, the negotiation context |
| **Project Lighthouse** (codename) | confidential ONLY: 8 | **entire existence** of the project name and what it refers to |
| **INC-2026-014** | confidential ONLY: 9 | **entire existence** of the incident and customer impact |

## Smoking-gun strings — these must NEVER appear in your view

If any of these strings surfaces in your graph, search results, entity
list, autocomplete, or any aggregation when you are signed in as the
test user, the ACL is leaking.

**From doc 6 (Bob PIP/comp):**
- `$385,000` — Bob's base salary
- `$145,000` — Bob's FY2025 bonus
- `$530,000` — Bob's FY2025 total comp
- `0.35%` — equity refresh
- `Founder dependence` (as a recurring board theme attached to Bob)
- `Performance improvement plan` (as a possibility for Bob)
- `Hiring quality` (as a concern attached to Bob)

**From doc 7 (Company B MSA):**
- `$2,840,000`, `$3,120,000`, `$3,420,000` — annual contract values
- `$340,000` — year-1 ramp credit
- `MFN clause` (Company B's specific concession)
- `9.8%` (the contractual escalation)

**From doc 8 (board minutes / M&A):**
- `Project Lighthouse` — codename
- `Company D` — the acquisition target
- `$48 million`, `$32 million`, `$16 million`, `$65 million` — deal terms
- `Munich` — Company D's location
- `Law firms` — Company D's customer segment

**From doc 9 (security incident):**
- `INC-2026-014`
- `identity-service v2.18.3`
- `cross-tenant`
- `1,400` (the volume of exposure)
- `Swedish data protection law`

**From doc 10 (restructuring):**
- `Eve`, `Frank` — affected employees
- `16 weeks of base pay`, `12 weeks of base pay`
- `$1.1 million`, `$340,000` — total restructuring cost
- `Q2 2026 restructuring`

## Smoking-gun strings — these SHOULD appear in your view

If these do NOT appear when expected, the ACL is over-filtering.

- `Company A`, `Bob`, `Carol`, `Grace`, `Dave` — appear in multiple
  `everyone` docs
- `Company B` — appears in docs 1, 3, 5 as a customer/partner
- `Marta` — appears in doc 3 as Company B's head of research engineering
- `Berlin`, `2019`, `Frankfurt` — founding-story facts from doc 1
- `BM25`, `reciprocal rank fusion`, `1024-dimensional` — engineering
  blog from doc 4
- `Q1 2026 all-hands` — doc 5 themes

## Derived-state-leak tests (the hard ones)

Beyond "does the confidential doc appear", these tests catch the subtler
class of bug we discussed — where an entity's summary, embedding, or
aggregate quietly absorbed confidential context.

1. **Bob's entity page.** Look at Bob's resolved entity. Visible facts
   must come ONLY from docs 1, 2, 3, 5. If the summary mentions
   compensation, the PIP, founder-dependence concerns, or M&A activity
   — leak. If Bob's "tags" or "props" include `confidential`, `pip`,
   `m&a` — leak.

2. **Bob's autocomplete / semantic neighbors.** Typing "Bob salary",
   "Bob performance", "Bob PIP" must not surface anything. Vector
   neighbors of "compensation review" must not include any Bob-related
   edge.

3. **Company B's entity page.** Visible facts must come ONLY from docs
   1, 3, 5. If the visible Company B summary mentions `$2,840,000`,
   `MFN`, `ramp credit`, or the incident — leak.

4. **Company D existence.** Search for "Company D", "Lighthouse",
   "Munich law firms", "acquisition target". Must return nothing. The
   entity itself must not be listed in any entity browser, autocomplete,
   or count.

5. **Eve / Frank existence.** Search for "Eve", "Frank", "layoff",
   "restructuring", "reduction in force". Must return nothing. Counts
   of headcount or employees must not include them.

6. **Incident existence.** Search for "INC-2026-014", "cross-tenant",
   "Swedish data protection". Must return nothing.

7. **Aggregations.** "How many customers does Company A have?",
   "Total contract value of customers" — must compute over only the
   facts visible to the caller. The answer must not encode confidential
   numbers indirectly.

8. **Provenance drill-in.** If any edge does appear (e.g., from public
   docs), the visible provenance must NOT show the confidential
   documents as sources, even by title.

9. **Bi-temporal history.** Time-travel queries (as-of past dates) must
   apply the same ACL — older versions of facts that came from
   confidential sources must not leak through history.

10. **Audit log.** The user's own audit log endpoint must not record
    or expose confidential-source provenance.

## How the docs got in

These episodes are inserted into the DB with their ACL rows attached,
bypassing the Drive sync path. `source_kind = 'test'`:

```sql
SELECT id, source_ref, processing_status FROM episode
WHERE workspace_id = '<your-ws>' AND source_kind = 'test'
ORDER BY source_ref;
```

To re-trigger extraction on all of them:

```sql
SELECT id FROM episode WHERE workspace_id = '<your-ws>' AND source_kind = 'test';
-- then for each id:
-- POST /api/episodes/{id}/reprocess
```

## What this corpus is and is not

This corpus is designed to test the **derived-state-leak** class of bugs
that comes from sharing a graph across ACL boundaries: the same entity
exists physically once, but the facts attached to it are partitioned
by visibility. Every leak in the matrix above is a real production-bug
shape worth catching.

This corpus is NOT a substitute for testing every ACL profile your
system supports (domain match, group match, etc.). The simplified
two-role model here makes the entity-collision tests crisp; expand the
ACL profiles separately if you need to exercise the predicate.
