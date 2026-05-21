---
title: Engineering blog — How we built hybrid retrieval at Company A
acl_profile: everyone
should_be_visible: true
visible_because: ace_kind='anyone' (public engineering blog post)
source_ref: blog-hybrid-retrieval
---

# How we built hybrid retrieval at Company A

*by Dave, retrieval lead*

When I joined Company A as the third engineer in 2019, the search layer
was a single PostgreSQL full-text index. It worked, in the sense that
queries returned within a few hundred milliseconds and the answers were
sometimes correct. It did not work, in the sense that "sometimes correct"
is a polite way of saying "not good enough to build a business on."

This post walks through how we got from that prototype to the hybrid
retrieval architecture that powers Company A today. It is intentionally
a deep technical piece — if you want the marketing version, read the
[product overview](/product) instead.

## The original problem

The original retrieval problem at Company A was deceptively simple:
given a natural-language query and a workspace's worth of documents,
return the top N most relevant facts. Two complications made this hard.

First, "facts" are not documents. A 40-page contract may contain three
relevant clauses; returning the whole document is useless. We had to
build a fact extraction pipeline that turned documents into
graph-shaped edges — subject, predicate, object — before retrieval
even started.

Second, "relevant" is not a single dimension. Lexical matches (BM25)
are great for unusual proper nouns and codenames; semantic matches
(vectors) are great for paraphrased questions where the exact wording
of the source does not appear in the query. Neither alone is enough.

## What hybrid means here

Our hybrid retriever runs three index types in parallel for every query:

1. A **BM25 index** over edge text, tuned for lexical recall.
2. A **dense vector index** over edge embeddings, using cosine
   similarity in a 1024-dimensional space.
3. A **graph traversal** that follows declared relationships from
   seed entities surfaced by the first two layers.

The three result sets are merged using reciprocal rank fusion (RRF)
with weights that we tune per workspace. The final list of candidate
edges is then re-ranked by a small cross-encoder and gated by the
permission layer before any results leave the box.

## Things we got wrong the first time

Three honest mistakes worth flagging, in case you are building something
similar:

**We tried to learn the fusion weights end-to-end.** It did not work.
RRF with fixed weights consistently beat the learned variants by 4-6
points on our benchmark. The learned model was overfitting to the
workspaces we had training labels for. Lesson: simple wins until your
data scale catches up.

**We re-embedded everything every time we changed model.** This was
embarrassingly expensive. We now version embeddings and migrate lazily
on read, only re-embedding edges that are actually retrieved. The cost
of running two embedding versions side by side is much less than the
cost of a full re-index.

**We treated permissions as a post-filter.** Two months in, we noticed
top-k results were inconsistent across users — not because the data
differed, but because the post-filter was dropping items below k. We
moved permission gating into the index scan. Latency went up by 8%.
Correctness went up by a lot more.

## Where we are now

The hybrid retriever is the second most important piece of Company A,
after extraction. It serves about 12 million queries per week across
all customer deployments, with p95 latency around 180 milliseconds for
medium-sized workspaces. Grace, our CTO, owns the cross-team roadmap
for retrieval; my team owns the implementation and the SLOs.

Next up: query-time graph expansion under ACL — i.e., letting graph
traversal cross permission boundaries safely. That is its own blog
post, and it is half written.

---

*Dave is the retrieval lead at Company A. He joined as the third
engineer in 2019 and has spent the last seven years arguing with Bob
about whether BM25 is dead.*
