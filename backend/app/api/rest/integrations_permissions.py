"""Integrations: per-episode permissions inspector.

GET /api/integrations/permissions

Returns one row per ingested episode in the current workspace along
with the ACL rows projected from the source system (Google Drive
permissions today). For each episode we also compute which workspace
members would currently see it under the Drive-style ACL filter, so
the admin can answer "who sees this doc?" without running a query
as each user.

Workspace-scoped. Owner/admin only — non-admins shouldn't see other
members' verified email addresses.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.auth.deps import CurrentPrincipal, DbSession

router = APIRouter(prefix="/integrations/permissions", tags=["integrations"])


@router.get("")
async def list_permissions(
    principal: CurrentPrincipal,
    session: DbSession,
    limit: int = Query(default=200, le=1000),
    only_with_acl: bool = Query(
        default=True,
        description=(
            "True (default): only episodes that carry external ACL rows. "
            "False: every episode, so admins can see manual ingests that "
            "fall under workspace-trust."
        ),
    ),
) -> dict[str, Any]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    if principal.role not in ("owner", "admin"):
        # Non-admins inspecting other members' verified emails is an
        # information leak. Stub a 403 rather than a 404 so the UI can
        # hide the link for non-admins instead of silently failing.
        raise HTTPException(403, "owner or admin required")

    # 1) Workspace members + their verified Google identities.
    member_rows = await session.execute(
        text(
            """
            SELECT u.id::text AS user_id,
                   u.email::text AS user_email,
                   wm.role AS role
            FROM workspace_member wm
            JOIN app_user u ON u.id = wm.user_id
            WHERE wm.workspace_id = CAST(:ws AS uuid)
              AND u.is_active = true
            ORDER BY wm.role, u.email
            """
        ),
        {"ws": principal.workspace_id},
    )
    members = [dict(r) for r in member_rows.mappings()]

    id_rows = await session.execute(
        text(
            """
            SELECT user_id::text AS user_id,
                   email::text AS email,
                   domain::text AS domain
            FROM user_external_identity
            WHERE workspace_id = CAST(:ws AS uuid)
            """
        ),
        {"ws": principal.workspace_id},
    )
    identities_by_user: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"emails": [], "domains": []}
    )
    for r in id_rows.mappings():
        uid = r["user_id"]
        if r["email"] and r["email"] not in identities_by_user[uid]["emails"]:
            identities_by_user[uid]["emails"].append(r["email"])
        if r["domain"] and r["domain"] not in identities_by_user[uid]["domains"]:
            identities_by_user[uid]["domains"].append(r["domain"])
    members_out = [
        {
            **m,
            "google_emails": identities_by_user[m["user_id"]]["emails"],
            "google_domains": identities_by_user[m["user_id"]]["domains"],
        }
        for m in members
    ]

    # 2) Episodes + their ACL rows (LEFT JOIN so we keep no-ACL episodes
    #    when only_with_acl=False).
    acl_filter = ""
    if only_with_acl:
        acl_filter = (
            "AND EXISTS (SELECT 1 FROM episode_external_acl x "
            "WHERE x.episode_id = ep.id)"
        )

    ep_rows = await session.execute(
        text(
            f"""
            SELECT ep.id::text AS id,
                   ep.source_kind AS source_kind,
                   ep.source_ref AS source_ref,
                   ep.ingested_at::text AS ingested_at,
                   LEFT(COALESCE(ep.content_text, ''), 80) AS snippet
            FROM episode ep
            WHERE ep.workspace_id = CAST(:ws AS uuid)
              AND ep.deleted_at IS NULL
              {acl_filter}
            ORDER BY ep.ingested_at DESC
            LIMIT :limit
            """
        ),
        {"ws": principal.workspace_id, "limit": limit},
    )
    episodes = [dict(r) for r in ep_rows.mappings()]
    if not episodes:
        return {"members": members_out, "episodes": []}

    ep_ids = [e["id"] for e in episodes]
    ace_rows = await session.execute(
        text(
            """
            SELECT episode_id::text AS episode_id,
                   ace_kind, email::text AS email, domain::text AS domain,
                   role, provider, source_doc_id, synced_at::text AS synced_at
            FROM episode_external_acl
            WHERE workspace_id = CAST(:ws AS uuid)
              AND episode_id::text = ANY(:ids)
            ORDER BY ace_kind, email NULLS LAST, domain NULLS LAST
            """
        ),
        {"ws": principal.workspace_id, "ids": ep_ids},
    )
    aces_by_ep: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ace_rows.mappings():
        aces_by_ep[r["episode_id"]].append(
            {
                "ace_kind": r["ace_kind"],
                "email": r["email"],
                "domain": r["domain"],
                "role": r["role"],
                "provider": r["provider"],
                "source_doc_id": r["source_doc_id"],
                "synced_at": r["synced_at"],
            }
        )

    # 3) Compute the visible-to-members set for each episode using the
    #    same predicate as the live retrieval path: episode visible iff
    #    no ACL rows OR ≥1 ACL row matches the member's identities.
    out: list[dict[str, Any]] = []
    for ep in episodes:
        aces = aces_by_ep.get(ep["id"], [])
        if not aces:
            # Workspace-trust fallback — every member sees it.
            visible_user_ids = [m["user_id"] for m in members]
        else:
            ace_kinds = {a["ace_kind"] for a in aces}
            ace_emails = {
                a["email"].lower() for a in aces if a["email"]
            }
            ace_domains = {
                a["domain"].lower() for a in aces if a["domain"]
            }
            visible_user_ids = []
            for m in members_out:
                if "anyone" in ace_kinds:
                    visible_user_ids.append(m["user_id"])
                    continue
                emails = {e.lower() for e in m["google_emails"]}
                domains = {d.lower() for d in m["google_domains"]}
                if emails & ace_emails or domains & ace_domains:
                    visible_user_ids.append(m["user_id"])

        out.append(
            {
                "id": ep["id"],
                "source_kind": ep["source_kind"],
                "source_ref": ep["source_ref"],
                "ingested_at": ep["ingested_at"],
                "snippet": ep["snippet"],
                "aces": aces,
                "visible_to_user_ids": visible_user_ids,
                "ace_summary": {
                    "anyone": sum(1 for a in aces if a["ace_kind"] == "anyone"),
                    "domain": sum(1 for a in aces if a["ace_kind"] == "domain"),
                    "user": sum(1 for a in aces if a["ace_kind"] == "user"),
                    "group": sum(1 for a in aces if a["ace_kind"] == "group"),
                },
            }
        )

    return {"members": members_out, "episodes": out}
