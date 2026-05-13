"""Workspace provisioning: create workspace + owner membership + seed ontology."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.ontology_seed import seed_workspace

log = get_logger(__name__)


@dataclass
class CreatedWorkspace:
    id: str
    slug: str
    name: str


async def create_workspace(
    session: AsyncSession,
    *,
    owner_user_id: str,
    slug: str,
    name: str,
) -> CreatedWorkspace:
    """Create workspace, add owner membership, seed ontology.

    Caller must have already bypassed RLS by connecting with a privileged
    session (no workspace_id set) — the app layer enforces this for new
    workspace creation flows.
    """
    result = await session.execute(
        text(
            """
            INSERT INTO workspace (slug, name)
            VALUES (:slug, :name)
            RETURNING id::text
            """
        ),
        {"slug": slug, "name": name},
    )
    workspace_id = result.scalar_one()

    await session.execute(
        text(
            """
            INSERT INTO workspace_member (workspace_id, user_id, role)
            VALUES (:ws, :user, 'owner')
            """
        ),
        {"ws": workspace_id, "user": owner_user_id},
    )

    # Seed ontology under the new workspace's scope.
    await session.execute(
        text("SELECT set_config('app.current_workspace_id', :ws, true)"),
        {"ws": workspace_id},
    )
    await seed_workspace(session, workspace_id)

    # Register the built-in action types so the kinetic action layer is
    # usable on first boot. Idempotent: ON CONFLICT (workspace_id, slug)
    # re-applies the schema if it changed in code.
    from app.domain import action as action_mod
    await action_mod.ensure_builtin_actions(session, workspace_id=workspace_id)

    log.info("workspace.created", id=workspace_id, slug=slug)
    return CreatedWorkspace(id=workspace_id, slug=slug, name=name)
