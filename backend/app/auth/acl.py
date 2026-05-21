"""Workspace-scoped visibility composer.

Three layers compose for every read path:

1. **Workspace RLS** (Postgres-enforced) — every row is scoped to
   ``workspace_id`` via ENABLE + FORCE row-level security. Even a query
   that forgets ``WHERE workspace_id = ...`` cannot leak across
   workspaces.
2. **Source ACL** (Drive permissions etc.) — episodes ingested via
   integrations carry per-document ACL rows in ``episode_external_acl``.
   At read time we intersect those rows with the caller's verified
   external identities (``user_external_identity``). See
   ``app.auth.external_acl``.
3. **Sensitivity labels + policy** — per-fact tagging applied in
   ``app.domain.sensitivity.apply_label_policy``. Owners/admins/service
   principals can bypass; orthogonal to source ACL.

The helpers here compose layers 2 into a SQL fragment. Service
principals (crawler workers, agent tokens marked ``kind='service'``)
bypass the source ACL — they rely on workspace RLS only. Callers must
pre-resolve identities via ``resolve_user_identities`` and pass them
in. The double lookup is intentional: one resolution per request, not
one per call site (hybrid retrieval has 5).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from app.auth.external_acl import (
    UserIdentities,
    edge_acl_predicate,
    episode_acl_predicate,
)
from app.auth.jwt import Principal


def edge_visibility_clause(
    principal: Principal | None,
    *,
    edge_alias: str = "edge",
    identities: UserIdentities | None = None,
    param_prefix: str = "acl",
) -> TextClause:
    """SQL fragment: is this edge visible to the caller under source ACL?

    Returns ``TRUE`` for:
      * Missing principal (background / system contexts).
      * Service principals (bypass the per-source filter).
      * Callers whose ``identities`` weren't resolved upfront — caller
        opted out of the filter (e.g. internal admin export). Workspace
        RLS still applies.

    Returns the full predicate when ``identities`` is provided, joining
    through ``edge → episode → episode_external_acl``.
    """
    if principal is None or principal.kind == "service" or identities is None:
        return text("TRUE")
    return edge_acl_predicate(
        edge_alias=edge_alias,
        identities=identities,
        param_prefix=param_prefix,
    )


def episode_visibility_clause(
    principal: Principal | None,
    *,
    episode_alias: str = "episode",
    identities: UserIdentities | None = None,
    param_prefix: str = "acl",
) -> TextClause:
    """SQL fragment: is this episode visible to the caller?

    Always includes the soft-delete filter. For user principals with
    resolved identities, also applies the source ACL predicate.
    """
    soft_delete = f"{episode_alias}.deleted_at IS NULL"
    if principal is None or principal.kind == "service" or identities is None:
        return text(soft_delete)
    acl = episode_acl_predicate(
        episode_alias=episode_alias,
        identities=identities,
        param_prefix=param_prefix,
    )
    return text(f"{soft_delete} AND ({acl.text})").bindparams(*acl._bindparams.values())
