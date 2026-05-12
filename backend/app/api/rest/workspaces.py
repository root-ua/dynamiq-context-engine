from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from dataclasses import asdict

from pydantic import BaseModel, Field

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
