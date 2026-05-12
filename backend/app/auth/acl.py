"""Per-source ACL filter composer.

Edges and entity_attributes inherit access from the source episode they
were extracted from. This module returns a SQL fragment that, AND'd into
a query's WHERE clause, restricts results to facts the principal can see.

The fragment references a table aliased as configured by the caller:
``edge_visibility_clause(principal, table_alias='e')`` produces SQL that
references ``e.source_id``. The caller is responsible for ensuring that
alias exists in their query.

Design choices:

* The principal is treated as an opaque carrier of identity. Bypass
  decisions (service kind, owner/admin role) are made here so callers
  don't need to remember them.
* The user-kind branch joins through ``user_external_identity`` to
  resolve the Dynamiq user to source-system principals. The join hits
  the ``user_external_identity_user_idx`` btree.
* ACL matches are union: a fact is visible if any matching ACL entry
  exists. Per spec, "visible if you can access at least one supporting
  source."
* In-workspace assertions (edges with no source episode, or whose source
  episode has no ``connector_instance_id``) are visible to any
  workspace member. Workspace RLS already gates that.
"""
from __future__ import annotations

from sqlalchemy import TextClause, text

from app.auth.jwt import Principal


def _bypasses_acl(principal: Principal) -> bool:
    """Owners, admins, and service-account principals are not subject to
    the per-source ACL filter. RLS still scopes them to the workspace.
    """
    if principal.kind == "service":
        return True
    if principal.role in ("owner", "admin"):
        return True
    return False


def edge_visibility_clause(
    principal: Principal,
    *,
    edge_alias: str = "edge",
) -> TextClause:
    """SQL fragment to AND into queries that select from ``edge``.

    The fragment is a single boolean expression — wrap with parens at
    the call site if combining with OR.

    Bypass: returns ``TRUE`` for owners/admins and service principals.

    User-kind principals see an edge iff:
    1. ``edge.source_id`` is NULL (no provenance — in-workspace
       assertion), OR
    2. The source episode has no connector binding (user/agent-asserted
       inside the workspace), OR
    3. The source episode has at least one ACL row that resolves to the
       caller's external identity (direct user, group member, domain,
       or anyone).
    """
    if _bypasses_acl(principal):
        return text("TRUE")

    return text(
        f"""
        (
          {edge_alias}.source_id IS NULL
          OR EXISTS (
            SELECT 1 FROM episode src
            WHERE src.id = {edge_alias}.source_id
              AND src.deleted_at IS NULL
              AND (
                src.connector_instance_id IS NULL
                OR EXISTS (
                  SELECT 1 FROM episode_acl ea
                  WHERE ea.episode_id = src.id
                    AND (
                      ea.principal_kind = 'anyone'
                      OR (ea.principal_kind = 'user'
                          AND ea.principal_external_id IN (
                            SELECT uei.external_id FROM user_external_identity uei
                            WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                            UNION ALL
                            SELECT uei.external_email FROM user_external_identity uei
                            WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                              AND uei.external_email IS NOT NULL
                          ))
                      OR (ea.principal_kind = 'group'
                          AND ea.principal_external_id IN (
                            SELECT grp->>'id'
                            FROM user_external_identity uei,
                                 jsonb_array_elements(uei.groups) grp
                            WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                            UNION ALL
                            SELECT grp->>'email'
                            FROM user_external_identity uei,
                                 jsonb_array_elements(uei.groups) grp
                            WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                              AND grp ? 'email'
                          ))
                      OR (ea.principal_kind = 'domain'
                          AND ea.principal_external_id IN (
                            SELECT split_part(uei.external_email, '@', 2)
                            FROM user_external_identity uei
                            WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                              AND uei.external_email IS NOT NULL
                          ))
                    )
                )
              )
          )
        )
        """
    ).bindparams(acl_user_id=principal.user_id)


def episode_visibility_clause(
    principal: Principal,
    *,
    episode_alias: str = "episode",
) -> TextClause:
    """SQL fragment to AND into queries that select from ``episode``.

    Visibility rule for a user-kind principal:
    * The episode has no connector binding (workspace-internal episode),
      OR
    * The episode has an ACL row that resolves to the caller's external
      identity.

    In both cases the episode must not be soft-deleted.

    Service/admin principals: TRUE.
    """
    if _bypasses_acl(principal):
        return text(f"{episode_alias}.deleted_at IS NULL OR TRUE")

    return text(
        f"""
        (
          {episode_alias}.deleted_at IS NULL
          AND (
            {episode_alias}.connector_instance_id IS NULL
            OR EXISTS (
              SELECT 1 FROM episode_acl ea
              WHERE ea.episode_id = {episode_alias}.id
                AND (
                  ea.principal_kind = 'anyone'
                  OR (ea.principal_kind = 'user'
                      AND ea.principal_external_id IN (
                        SELECT uei.external_id FROM user_external_identity uei
                        WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                        UNION ALL
                        SELECT uei.external_email FROM user_external_identity uei
                        WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                          AND uei.external_email IS NOT NULL
                      ))
                  OR (ea.principal_kind = 'group'
                      AND ea.principal_external_id IN (
                        SELECT grp->>'id'
                        FROM user_external_identity uei,
                             jsonb_array_elements(uei.groups) grp
                        WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                        UNION ALL
                        SELECT grp->>'email'
                        FROM user_external_identity uei,
                             jsonb_array_elements(uei.groups) grp
                        WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                          AND grp ? 'email'
                      ))
                  OR (ea.principal_kind = 'domain'
                      AND ea.principal_external_id IN (
                        SELECT split_part(uei.external_email, '@', 2)
                        FROM user_external_identity uei
                        WHERE uei.user_id = CAST(:acl_user_id AS uuid)
                          AND uei.external_email IS NOT NULL
                      ))
                )
            )
          )
        )
        """
    ).bindparams(acl_user_id=principal.user_id)
