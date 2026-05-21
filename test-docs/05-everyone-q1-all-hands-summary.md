---
title: Q1 2026 all-hands — public summary
acl_profile: everyone
should_be_visible: true
visible_because: ace_kind='anyone' (sanitized public version of all-hands deck)
source_ref: q1-2026-all-hands-public-summary
---

# Q1 2026 all-hands — public summary

This is the public-friendly summary of Company A's Q1 2026 all-hands,
posted to the company website for customers, prospects, and the broader
community. The internal version covers numbers and decisions that are
not appropriate to share externally; this version covers the themes we
are happy to publish.

Presented by Bob (CEO), Carol (CFO), Grace (CTO), and Dave (retrieval).

## Theme of the quarter: depth over breadth

Bob opened by reiterating that Company A is still deliberately a
small-customer-count, high-engagement business. We added a small number
of new customer logos in Q1; the larger part of our growth came from
existing customers — most visibly Company B, whose expanded partnership
was announced publicly in February, and Company C, whose deployment
crossed an important internal milestone in March.

Bob's framing: "We do not need to be in every RFP. We need to be the
right answer for the customers who care about getting context right.
The number of customers we have is not the metric. The depth at which
those customers use us is."

## Engineering theme: permissions become first-class

Grace walked through the architecture work in Q1. The headline:
permissions are no longer a thing that lives "next to" retrieval — they
are now part of the index scan itself. Dave's team rebuilt the hybrid
retriever to push the permission predicate into the lowest layer of the
query plan. This was a multi-quarter project finishing in Q1.

The reason this matters publicly: customers in regulated industries
have been asking for ACL guarantees we could not honestly make before.
Now we can. Expect a more concrete public commitment on permissions
correctness later in the year.

## Customer theme: time matters

Several customers in Q1 reported what we have started calling "stale
answer" complaints — cases where the system correctly retrieved a fact,
but the fact was no longer current. Our bi-temporal model already
distinguishes "when something was true" from "when we believed it";
Q1's customer-facing work was about making this distinction visible in
the answer itself. The new freshness indicators rolled out in late
March and have measurably reduced these complaints.

Company C in particular drove a lot of this work. Their workflows
touch documents with explicit expiration dates, and our previous
default of "show the most recently believed fact" was not honest enough.

## Hiring

Carol announced that the company will hire roughly 12 more people in
2026, weighted toward retrieval, customer engineering, and the
European customer-facing team. We are not pursuing aggressive headcount
growth; the bar stays high.

## Q&A — selected questions

**"Are we going to open-source any part of the platform?"** Bob: not
this year. We may open a small SDK in 2027 if and only if it makes
existing customers more successful. We are not interested in
open-sourcing for marketing reasons.

**"What do customers complain about most?"** Grace: setup friction
on the first few connectors, and the freshness issue mentioned above.
Both are being addressed.

**"What is the one thing we will be proud of at the end of 2026?"**
Bob: that customers in regulated industries trust Company A enough
that we are the default rather than the exception. He acknowledged
this is a multi-year theme and not something Q4 will settle.

## Next all-hands

Q2 all-hands is scheduled for the second week of July. As always,
the internal version will be on the day; this public summary will
follow about a week later.
