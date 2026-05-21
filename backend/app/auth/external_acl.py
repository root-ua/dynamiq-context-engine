"""Drive-style external ACL — caller-identity-based row visibility.

Episode (and therefore edge) visibility for users authenticated via the
session JWT is the union of:

1. **Workspace trust** — episodes with zero ``episode_external_acl`` rows
   (manual ingests, agent writes) are visible to all workspace members.
2. **Source ACL match** — episodes that DO have ACL rows are visible only
   when at least one row matches the caller:

   - ``ace_kind='anyone'`` → visible to every workspace member.
   - ``ace_kind='domain'`` → visible if the caller has a verified Google
     identity in that domain.
   - ``ace_kind IN ('user','group')`` → visible if the caller has a
     verified Google identity with that exact email.

Service principals bypass the filter entirely — they rely on workspace
RLS only. This is the contract for crawler workers that must ingest
content regardless of who can later read it.

The caller's verified identities are resolved from ``user_external_identity``,
populated by the OAuth callback.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from app.auth.jwt import Principal


@dataclass(frozen=True)
class UserIdentities:
    """A workspace user's verified external identities for ACL matching."""

    emails: list[str]
    domains: list[str]


async def resolve_user_identities(
    session: AsyncSession, principal: Principal
) -> UserIdentities:
    """Return the caller's identity for ACL matching: app email + its domain.

    Pipeshub-style strict matching. The app login email is the SINGLE source
    of identity for ACL purposes — there is no OAuth bridge to map a workspace
    user to additional Google identities. A workspace member sees a
    Drive-sourced episode iff the episode's ACL explicitly references their
    app email (or their email's domain, or 'anyone').

    Tradeoff: a user whose Drive content is shared with a different email
    (personal Gmail, work alias) cannot see it via the workspace — they must
    re-share the doc in Drive against their app email. Failure mode is
    "empty results" rather than "wrong results", which is the safer error.

    Service principals return empty lists and rely on workspace RLS only.
    """
    del session  # kept in signature for API stability; no DB hit needed
    if (
        principal.kind != "user"
        or not principal.email
    ):
        return UserIdentities(emails=[], domains=[])
    email = principal.email.strip().lower()
    domain = email.split("@", 1)[1] if "@" in email else ""
    return UserIdentities(
        emails=[email],
        domains=[domain] if domain else [],
    )


def episode_acl_predicate(
    *,
    episode_alias: str,
    identities: UserIdentities,
    param_prefix: str = "acl",
) -> TextClause:
    """SQL predicate: ``<episode>`` is visible under external ACL.

    True iff the episode has no external ACL rows (= workspace-trust
    fallback) OR at least one of its ACL rows matches the caller.

    Returns a ``TextClause`` with the bind params pre-attached so
    callers don't need to thread them through.
    """
    emails_param = f"{param_prefix}_emails"
    domains_param = f"{param_prefix}_domains"
    sql = f"""
    (
      NOT EXISTS (
        SELECT 1 FROM episode_external_acl x
        WHERE x.episode_id = {episode_alias}.id
      )
      OR EXISTS (
        SELECT 1 FROM episode_external_acl ea
        WHERE ea.episode_id = {episode_alias}.id
          AND (
            ea.ace_kind = 'anyone'
            OR (ea.ace_kind = 'domain'
                AND ea.domain = ANY(CAST(:{domains_param} AS citext[])))
            OR (ea.ace_kind IN ('user', 'group')
                AND ea.email = ANY(CAST(:{emails_param} AS citext[])))
          )
      )
    )
    """
    clause = text(sql).bindparams(
        bindparam(emails_param, value=identities.emails),
        bindparam(domains_param, value=identities.domains),
    )
    return clause


def edge_acl_predicate(
    *,
    edge_alias: str,
    identities: UserIdentities,
    param_prefix: str = "acl",
) -> TextClause:
    """SQL predicate: edge is visible under external ACL.

    An edge is visible iff its source episode is visible. Edges with no
    source (or source_kind != 'episode') fall through workspace-trust —
    they have no Drive ACL to match against.
    """
    emails_param = f"{param_prefix}_emails"
    domains_param = f"{param_prefix}_domains"
    sql = f"""
    (
      {edge_alias}.source_id IS NULL
      OR {edge_alias}.source_kind <> 'episode'
      OR EXISTS (
        SELECT 1 FROM episode ep
        WHERE ep.id = {edge_alias}.source_id
          AND (
            NOT EXISTS (
              SELECT 1 FROM episode_external_acl x WHERE x.episode_id = ep.id
            )
            OR EXISTS (
              SELECT 1 FROM episode_external_acl ea
              WHERE ea.episode_id = ep.id
                AND (
                  ea.ace_kind = 'anyone'
                  OR (ea.ace_kind = 'domain'
                      AND ea.domain = ANY(CAST(:{domains_param} AS citext[])))
                  OR (ea.ace_kind IN ('user', 'group')
                      AND ea.email = ANY(CAST(:{emails_param} AS citext[])))
                )
            )
          )
      )
    )
    """
    clause = text(sql).bindparams(
        bindparam(emails_param, value=identities.emails),
        bindparam(domains_param, value=identities.domains),
    )
    return clause
