---
title: CONFIDENTIAL — Security incident postmortem (INC-2026-014)
acl_profile: confidential
should_be_visible: false
visible_because: restricted to security incident response team only — must NOT appear for ordinary workspace users
source_ref: incident-postmortem-2026-014
acl_user: security-irt@company-a.example
---

# CONFIDENTIAL — Postmortem: INC-2026-014

**Incident ID:** INC-2026-014
**Severity:** SEV-1
**Date of incident:** 2026-04-22, 14:18 UTC to 17:42 UTC
**Customers affected:** Company B, Company C
**Postmortem owner:** Grace (CTO)
**Distribution:** Security incident response team, named executives,
and the assigned legal counsel. This document contains specific
attribution of a security incident to named customers and is subject
to both companies' breach-notification clauses. Do NOT share outside
the explicit distribution list.

## Summary

On 2026-04-22, a misconfigured permission policy in Company A's
identity service caused a 3.4-hour window during which retrieval
queries from one tenant could, under specific query patterns, return
metadata snippets from a different tenant.

The bug affected Company B and Company C. No primary document content
was exposed; the leak was limited to entity names, document titles,
and counts. The volume of exposure was small (approximately 1,400
queries returned cross-tenant snippets), but the exposure is
nonetheless reportable under both customers' contracts and likely
under regulatory regimes applicable to Company B in particular.

## Timeline (UTC)

- **14:11** Routine deploy of identity-service v2.18.3 to production.
- **14:18** First cross-tenant snippet returned. The exposure begins.
- **15:42** First customer complaint received from a Company B
  research analyst whose query returned what looked like an unrelated
  document title.
- **15:48** On-call engineer paged. Initial diagnosis: "result
  ranking bug, not security."
- **16:11** Second complaint, this time from Company C, with a
  clearer pattern: a query for "freshness policy" returned a snippet
  that the user did not recognize as belonging to their workspace.
- **16:14** Grace paged. Severity escalated to SEV-1.
- **16:23** Production traffic to identity-service halted; queries
  fall back to the previous version.
- **17:42** All affected tenants confirmed clean; incident resolved.

## Root cause

The identity-service v2.18.3 deploy introduced a regression in the
permission resolver that, under a specific combination of query
shape and cache state, would evaluate the permission predicate
against the wrong workspace ID. The bug was a one-line ordering
issue in a refactor of the cache key construction.

The bug shipped because:

1. The unit test that would have caught the bug did exist but was
   skipped during the refactor — Dave's team had marked it as a
   flake earlier in the quarter without filing a follow-up.
2. The integration test environment uses a single tenant by default
   and did not exercise the cross-tenant path.
3. The deploy ran during normal traffic rather than during a low-
   traffic window, accelerating the exposure rate.

The skipped unit test, the single-tenant integration environment,
and the deploy timing each individually would not have prevented the
incident; the combination did.

## Customer impact

**Company B.** Approximately 870 queries from Company B users
returned snippets whose origin was Company C. The snippets contained
no primary document content, but did contain document titles and
entity names from Company C's workspace. Company B's executive
sponsor was notified by Bob personally at 18:30 on the day of the
incident. Formal written notification was delivered the following
morning. Company B's contract requires notification within 24 hours;
we met this requirement.

**Company C.** Approximately 530 queries from Company C users
returned snippets whose origin was Company B. Symmetric exposure
profile. Company C's executive sponsor was notified by Carol
personally at 18:45. Formal written notification followed within 24
hours.

No personal data was exposed in either direction beyond what is
inherent in document titles and entity names.

## Regulatory implications

Counsel (external) has advised that Company B's notification
obligations under Swedish data protection law may require a filing
to the supervisory authority within 72 hours. A draft filing was
prepared and held pending Company B's own assessment of materiality.
Company B confirmed on 2026-04-25 that they would file independently
and that Company A's separate filing was not required.

Company C is not subject to an equivalent independent filing
obligation in this case.

## Remediation

Completed within 7 days of the incident:
- The skipped unit test re-enabled and the underlying flake fixed.
- The integration test environment expanded to include three
  tenants by default.
- All deploys to identity-service now require a multi-tenant
  rehearsal in staging before production rollout.

Completed within 30 days of the incident:
- A second permission predicate has been added at the storage
  layer as defense in depth, independent of the identity-service
  cache.
- The permission audit log now records the resolved workspace ID
  for every query, enabling retrospective detection of mismatches.

## Confidentiality

The fact of this incident, the customer attribution, and the
specific numbers above are confidential to the named distribution.
Public communications about the incident, if any, will be drafted
by Bob and reviewed by counsel before release.

No reference to Company B or Company C as affected parties is
appropriate in any other internal document or workspace.
