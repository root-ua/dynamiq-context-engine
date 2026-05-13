"""Workspace-scoped visibility composer.

The platform delegates upstream-system ACLs to the calling agent
(Claude Code, ChatGPT, etc.) — the agent decides what to ingest. Once
a fact lands in the graph, visibility is determined by:

1. **Workspace RLS** (enforced in Postgres) — every row is scoped to
   ``workspace_id`` and only workspace members can see it.
2. **Sensitivity labels + policy** (see ``app.domain.sensitivity``) —
   layered on top by query-time filtering.

There is no per-fact source-system ACL. The visibility helpers here
exist to keep the call sites of edge / episode queries uniform — they
all build a SQL fragment that boils down to ``TRUE`` after RLS does
its work. Owners, admins, and service principals bypass the label
policy elsewhere; that bypass is centralized in
``app.domain.sensitivity.apply_label_policy``.
"""
from __future__ import annotations

from sqlalchemy import TextClause, text

from app.auth.jwt import Principal


def edge_visibility_clause(
    principal: Principal,
    *,
    edge_alias: str = "edge",
) -> TextClause:
    """SQL fragment for edge visibility — workspace RLS does the work,
    so this is always ``TRUE``. Kept as a function so callers don't
    need a special branch for the principal-free case.
    """
    del principal, edge_alias
    return text("TRUE")


def episode_visibility_clause(
    principal: Principal,
    *,
    episode_alias: str = "episode",
) -> TextClause:
    """SQL fragment for episode visibility — soft-delete filter only.
    Workspace RLS handles the rest.
    """
    del principal
    return text(f"{episode_alias}.deleted_at IS NULL")
