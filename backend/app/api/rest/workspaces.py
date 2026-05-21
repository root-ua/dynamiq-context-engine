from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.rest.schemas import (
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceSettingsUpdate,
)
from app.auth.deps import CurrentPrincipal, DbSession
from app.core.logging import get_logger
from app.db.session import session_scope
from app.domain.demo_seeder import seed_demo_workspace
from app.domain.workspace import create_workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

log = get_logger(__name__)


class WorkspaceDeleteConfirm(BaseModel):
    slug: str = Field(min_length=1, max_length=80)


def _require_path_matches_principal(
    workspace_id: str, principal_workspace_id: str | None
) -> None:
    """The URL path's workspace_id must equal the principal's resolved
    workspace (which `current_principal` already verified membership for).

    The `workspace` table has no RLS (it's a shared table), so these
    endpoints must enforce tenancy at the app layer.
    """
    if principal_workspace_id != workspace_id:
        raise HTTPException(
            status_code=403,
            detail="not authorized for this workspace",
        )


@router.get("")
async def list_my_workspaces(principal: CurrentPrincipal) -> list[WorkspaceOut]:
    # Workspace listing runs without RLS scoping so users can see all their memberships.
    async with session_scope(user_id=principal.user_id) as session:
        result = await session.execute(
            text(
                """
                SELECT w.id::text, w.slug, w.name, w.settings,
                       w.created_at::text
                FROM workspace w
                JOIN workspace_member m ON m.workspace_id = w.id
                WHERE m.user_id = :user AND w.deleted_at IS NULL
                ORDER BY w.created_at
                """
            ),
            {"user": principal.user_id},
        )
        return [WorkspaceOut(**dict(r)) for r in result.mappings()]


@router.post("", status_code=201)
async def create(
    payload: WorkspaceCreate, principal: CurrentPrincipal
) -> WorkspaceOut:
    # Agent tokens can't create workspaces.
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot create workspaces")

    async with session_scope(user_id=principal.user_id) as session:
        try:
            ws = await create_workspace(
                session,
                owner_user_id=principal.user_id,
                slug=payload.slug,
                name=payload.name,
            )
        except Exception as exc:
            # Never echo raw DB errors — they can leak schema details.
            log.warning("workspace.create.failed", error=str(exc))
            raise HTTPException(400, "failed to create workspace") from exc

        # Seed initial settings with chosen ontology mode.
        await session.execute(
            text(
                """
                UPDATE workspace
                SET settings = jsonb_set(
                  COALESCE(settings, '{}'::jsonb),
                  '{ontology_mode}',
                  to_jsonb(CAST(:mode AS text))
                )
                WHERE id = :id
                """
            ),
            {"id": ws.id, "mode": payload.ontology_mode},
        )

        result = await session.execute(
            text("SELECT id::text, slug, name, settings, created_at::text FROM workspace WHERE id = :id"),
            {"id": ws.id},
        )
        row = result.mappings().one()
        return WorkspaceOut(**dict(row))


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> WorkspaceOut:
    _require_path_matches_principal(workspace_id, principal.workspace_id)
    result = await session.execute(
        text(
            "SELECT id::text, slug, name, settings, created_at::text "
            "FROM workspace WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": workspace_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "workspace not found")
    return WorkspaceOut(**dict(row))


@router.delete("/{workspace_id}", status_code=204, response_class=Response)
async def delete_workspace(
    workspace_id: str,
    payload: WorkspaceDeleteConfirm,
    principal: CurrentPrincipal,
    session: DbSession,
) -> None:
    """Soft-delete a workspace. Only the owner can do this.

    We soft-delete (`deleted_at = now()`) rather than cascade-drop because
    Yjs documents may be open in someone's browser; surviving the
    soft-delete lets them save-and-close cleanly. Scheduled hard-delete
    is a follow-up (worker job).

    Requires a confirmation payload `{slug: <the-workspace-slug>}` — the
    UI forces the user to type the slug before enabling the button.
    """
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot delete workspaces")
    _require_path_matches_principal(workspace_id, principal.workspace_id)

    # Ownership check.
    async with session_scope(user_id=principal.user_id) as owner_session:
        r = await owner_session.execute(
            text(
                "SELECT role FROM workspace_member "
                "WHERE workspace_id = CAST(:w AS uuid) "
                "AND user_id = CAST(:u AS uuid)"
            ),
            {"w": workspace_id, "u": principal.user_id},
        )
        row = r.first()
        if not row or row[0] != "owner":
            raise HTTPException(
                status_code=403,
                detail="only the workspace owner can delete",
            )

    # Slug confirmation.
    r = await session.execute(
        text("SELECT slug FROM workspace WHERE id = :id"),
        {"id": workspace_id},
    )
    row = r.first()
    if not row:
        raise HTTPException(404, "workspace not found")
    if payload.slug != row[0]:
        raise HTTPException(
            status_code=400,
            detail="slug confirmation does not match",
        )

    await session.execute(
        text("UPDATE workspace SET deleted_at = now() WHERE id = :id"),
        {"id": workspace_id},
    )
    log.info("workspace.soft_delete", workspace_id=workspace_id)


@router.post("/{workspace_id}/debug-reset")
async def debug_reset(
    workspace_id: str,
    payload: WorkspaceDeleteConfirm,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, int]:
    """Wipe the graph, episodes, and ontology in this workspace.

    Owner-only. Requires the slug confirmation payload — same shape as
    the delete endpoint. Preserves:
      - the workspace itself, its members, settings, OAuth connections
      - sensitivity labels and label policies
      - audit log (this reset is itself logged)

    Deletes (in FK-safe order):
      - pending facts, edges, edge labels
      - entity external refs, entity labels, entity resolver cache, entities
      - relation types, entity types (ontology)
      - episode external ACL, episode labels, google_doc_sync_state
      - prov_activity_derivation, prov_activity
      - episodes

    After this, the workspace is structurally identical to a freshly
    seeded one — re-clicking 'Sync now' on an OAuth connection
    re-ingests every doc as if it had never been seen.
    """
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot reset workspaces")
    _require_path_matches_principal(workspace_id, principal.workspace_id)

    async with session_scope(user_id=principal.user_id) as owner_session:
        r = await owner_session.execute(
            text(
                "SELECT role FROM workspace_member "
                "WHERE workspace_id = CAST(:w AS uuid) "
                "AND user_id = CAST(:u AS uuid)"
            ),
            {"w": workspace_id, "u": principal.user_id},
        )
        row = r.first()
        if not row or row[0] != "owner":
            raise HTTPException(403, "only the workspace owner can reset")

    r = await session.execute(
        text("SELECT slug FROM workspace WHERE id = :id"),
        {"id": workspace_id},
    )
    row = r.first()
    if not row:
        raise HTTPException(404, "workspace not found")
    if payload.slug != row[0]:
        raise HTTPException(400, "slug confirmation does not match")

    ws = {"ws": workspace_id}
    counts: dict[str, int] = {}

    # Order: dependents first. Workspace RLS scopes us, but we pass
    # workspace_id explicitly as defense in depth.
    delete_steps = [
        # Graph dependents
        ("agent_tool_call",
         "DELETE FROM agent_tool_call WHERE workspace_id = CAST(:ws AS uuid)"),
        ("action_invocation",
         "DELETE FROM action_invocation WHERE workspace_id = CAST(:ws AS uuid)"),
        ("pending_fact",
         "DELETE FROM pending_fact WHERE workspace_id = CAST(:ws AS uuid)"),
        ("edge_label",
         "DELETE FROM edge_label WHERE workspace_id = CAST(:ws AS uuid)"),
        ("edge",
         "DELETE FROM edge WHERE workspace_id = CAST(:ws AS uuid)"),
        # Entity dependents
        ("entity_attribute",
         "DELETE FROM entity_attribute WHERE workspace_id = CAST(:ws AS uuid)"),
        ("entity_external_ref",
         "DELETE FROM entity_external_ref WHERE workspace_id = CAST(:ws AS uuid)"),
        ("entity_resolution_decision",
         "DELETE FROM entity_resolution_decision WHERE workspace_id = CAST(:ws AS uuid)"),
        ("block_entity_ref",
         "DELETE FROM block_entity_ref WHERE block_id IN "
         "(SELECT id FROM block WHERE workspace_id = CAST(:ws AS uuid))"),
        ("entity",
         "DELETE FROM entity WHERE workspace_id = CAST(:ws AS uuid)"),
        # Ontology — entity_type has three FKs pointing at it from other
        # tables, none of which have ON DELETE behavior:
        #   1. entity_type.extends_id → entity_type.id  (self)
        #   2. relation_type.domain_type_id → entity_type.id
        #   3. relation_type.range_type_id  → entity_type.id
        # All three FKs are global (not workspace-scoped). Older data
        # contains cross-workspace references — another workspace's
        # relation_type may extend or domain-bind to our entity_type. NULL
        # every reference TO our types before deleting, regardless of which
        # workspace the referring row lives in. That's heavier than usual
        # but unavoidable for a "reset OUR data" semantic given the schema.
        ("relation_type",
         "DELETE FROM relation_type WHERE workspace_id = CAST(:ws AS uuid)"),
        ("entity_type:break_extends",
         "UPDATE entity_type SET extends_id = NULL "
         "WHERE extends_id IN (SELECT id FROM entity_type "
         "WHERE workspace_id = CAST(:ws AS uuid))"),
        ("entity_type:break_relation_domain",
         "UPDATE relation_type SET domain_type_id = NULL "
         "WHERE domain_type_id IN (SELECT id FROM entity_type "
         "WHERE workspace_id = CAST(:ws AS uuid))"),
        ("entity_type:break_relation_range",
         "UPDATE relation_type SET range_type_id = NULL "
         "WHERE range_type_id IN (SELECT id FROM entity_type "
         "WHERE workspace_id = CAST(:ws AS uuid))"),
        ("entity_type",
         "DELETE FROM entity_type WHERE workspace_id = CAST(:ws AS uuid)"),
        # Document / block dependents (must drop before episode)
        ("block",
         "DELETE FROM block WHERE workspace_id = CAST(:ws AS uuid)"),
        ("document_revision",
         "DELETE FROM document_revision WHERE document_id IN "
         "(SELECT id FROM document WHERE workspace_id = CAST(:ws AS uuid))"),
        ("document",
         "DELETE FROM document WHERE workspace_id = CAST(:ws AS uuid)"),
        # Episode dependents
        ("episode_external_acl",
         "DELETE FROM episode_external_acl WHERE workspace_id = CAST(:ws AS uuid)"),
        ("episode_label",
         "DELETE FROM episode_label WHERE workspace_id = CAST(:ws AS uuid)"),
        ("google_doc_sync_state",
         "DELETE FROM google_doc_sync_state WHERE workspace_id = CAST(:ws AS uuid)"),
        ("google_docs_sync_job",
         "DELETE FROM google_docs_sync_job WHERE workspace_id = CAST(:ws AS uuid)"),
        # Provenance — derivation table has its own workspace_id column;
        # FKs to prov_activity already cascade, but explicit cleanup keeps
        # the rowcount visible in the audit log.
        ("prov_activity_derivation",
         "DELETE FROM prov_activity_derivation WHERE workspace_id = CAST(:ws AS uuid)"),
        ("prov_activity",
         "DELETE FROM prov_activity WHERE workspace_id = CAST(:ws AS uuid)"),
        # Episode last
        ("episode",
         "DELETE FROM episode WHERE workspace_id = CAST(:ws AS uuid)"),
    ]

    # Each step runs inside its own SAVEPOINT. A failure rolls back the
    # savepoint only — the outer transaction stays alive so later steps
    # still execute. Without this, the first missing table or FK collision
    # aborts the whole transaction and every subsequent DELETE silently
    # no-ops with "current transaction is aborted".
    for name, sql in delete_steps:
        try:
            async with session.begin_nested():
                result = await session.execute(text(sql), ws)
                counts[name] = result.rowcount or 0
        except Exception as exc:
            log.warning(
                "workspace.debug_reset.step_failed",
                table=name, error=str(exc),
            )
            counts[name] = -1

    # Clear the selection on any OAuth connections so the next sync
    # is a clean "what should I pull?" rather than re-pulling the old set.
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE google_drive_connection "
                    "SET selection = '{\"folders\":[],\"files\":[]}'::jsonb "
                    "WHERE workspace_id = CAST(:ws AS uuid)"
                ),
                ws,
            )
    except Exception:
        pass  # connection table may not exist

    # Audit row so the reset is forensically visible.
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    """
                    INSERT INTO audit_log
                      (workspace_id, actor_kind, actor_id, action,
                       target_kind, target_id, diff)
                    VALUES (CAST(:ws AS uuid), 'user', CAST(:actor AS uuid),
                            'workspace.debug_reset', 'workspace',
                            CAST(:ws AS uuid),
                            CAST(:counts AS jsonb))
                    """
                ),
                {
                    "ws": workspace_id,
                    "actor": principal.user_id,
                    "counts": _json(counts),
                },
            )
    except Exception as exc:
        log.warning("workspace.debug_reset.audit_failed", error=str(exc))

    log.info(
        "workspace.debug_reset.done",
        workspace_id=workspace_id, counts=counts,
    )
    return counts


def _json(obj: object) -> str:
    import json as _json_mod
    return _json_mod.dumps(obj)


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceSettingsUpdate,
    principal: CurrentPrincipal,
    session: DbSession,
) -> WorkspaceOut:
    _require_path_matches_principal(workspace_id, principal.workspace_id)

    # Separate single-field updates — avoids dynamic SQL string building.
    if payload.name is not None:
        await session.execute(
            text("UPDATE workspace SET name = :name WHERE id = :id"),
            {"id": workspace_id, "name": payload.name},
        )
    if payload.ontology_mode is not None:
        await session.execute(
            text(
                """
                UPDATE workspace
                SET settings = jsonb_set(
                    COALESCE(settings, '{}'::jsonb),
                    '{ontology_mode}',
                    to_jsonb(CAST(:mode AS text))
                )
                WHERE id = :id
                """
            ),
            {"id": workspace_id, "mode": payload.ontology_mode},
        )
    if payload.high_sensitivity is not None:
        await session.execute(
            text(
                "UPDATE workspace SET high_sensitivity = :flag WHERE id = :id"
            ),
            {"id": workspace_id, "flag": payload.high_sensitivity},
        )

    result = await session.execute(
        text("SELECT id::text, slug, name, settings, created_at::text FROM workspace WHERE id = :id"),
        {"id": workspace_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "workspace not found")
    return WorkspaceOut(**dict(row))


@router.post("/{workspace_id}/seed-demo", status_code=201)
async def seed_demo(
    workspace_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict:
    """Populate this workspace with the Halcyon Labs demo dataset.

    Idempotent: calling twice doesn't duplicate entities. Requires the
    caller to be on a BetterAuth session (not an agent token) and to
    match the path's workspace id.
    """
    if principal.claims.get("kind") == "agent_token":
        raise HTTPException(403, "agent tokens cannot seed demo data")
    _require_path_matches_principal(workspace_id, principal.workspace_id)

    try:
        result = await seed_demo_workspace(
            session,
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
        )
    except Exception as exc:
        log.exception("workspace.seed_demo.failed", workspace_id=workspace_id)
        raise HTTPException(
            status_code=500,
            detail=f"demo seed failed: {exc}",
        ) from exc
    return asdict(result)
