"""CLI for seeding the Halcyon demo dataset into a workspace.

Run from inside the backend container:

    # create a fresh demo workspace owned by an existing user
    python -m app.scripts.seed_demo create --owner-email me@example.com

    # populate an existing (empty) workspace
    python -m app.scripts.seed_demo populate --workspace-id <uuid>

    # wipe + reseed a demo workspace (dev only)
    python -m app.scripts.seed_demo reset --workspace-slug demo-halcyon-abc
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

from sqlalchemy import text

from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.domain.demo_seeder import seed_demo_workspace
from app.domain.workspace import create_workspace

log = get_logger(__name__)


def _mk_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="seed_demo")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Create a new demo workspace + seed it.")
    c.add_argument("--owner-email", required=True, help="existing user's email")
    c.add_argument(
        "--slug",
        default=None,
        help="workspace slug (default: demo-halcyon-<short>)",
    )
    c.add_argument(
        "--name",
        default="Demo — Halcyon Labs",
        help="workspace display name",
    )

    pp = sub.add_parser("populate", help="Seed an existing workspace.")
    pp.add_argument("--workspace-id", required=True)

    r = sub.add_parser("reset", help="Wipe + reseed a workspace by slug.")
    r.add_argument("--workspace-slug", required=True)

    return p


async def _cmd_create(args: argparse.Namespace) -> None:
    slug = args.slug or f"demo-halcyon-{uuid4().hex[:6]}"
    async with session_scope() as session:
        r = await session.execute(
            text("SELECT id::text FROM app_user WHERE email = :email"),
            {"email": args.owner_email},
        )
        row = r.first()
        if not row:
            raise SystemExit(
                f"no app_user found with email={args.owner_email!r}. "
                "Create the account first via signup, then rerun."
            )
        owner_id = row[0]

        ws = await create_workspace(
            session, owner_user_id=owner_id, slug=slug, name=args.name
        )
        await session.execute(
            text(
                "SELECT set_config('app.current_workspace_id', :ws, true)"
            ),
            {"ws": ws.id},
        )
        result = await seed_demo_workspace(
            session, workspace_id=ws.id, actor_user_id=owner_id
        )
    print(
        f"ok. workspace_id={ws.id} slug={ws.slug} name={ws.name!r}\n"
        f"  entities={result.entities_created}+{result.entities_updated}updated "
        f"edges={result.edges_created} "
        f"docs={result.documents_created} episodes={result.episodes_created} "
        f"sessions={result.agent_sessions_created}\n"
        f"  home_doc={result.home_document_id}"
    )


async def _cmd_populate(args: argparse.Namespace) -> None:
    async with session_scope() as session:
        r = await session.execute(
            text(
                "SELECT id::text, slug FROM workspace "
                "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
            ),
            {"id": args.workspace_id},
        )
        row = r.first()
        if not row:
            raise SystemExit(f"workspace {args.workspace_id} not found")
        # Pick any owner as the "actor" for created_by fields.
        owner = await session.execute(
            text(
                "SELECT user_id::text FROM workspace_member "
                "WHERE workspace_id = CAST(:id AS uuid) AND role = 'owner' "
                "LIMIT 1"
            ),
            {"id": args.workspace_id},
        )
        owner_row = owner.first()
        if not owner_row:
            raise SystemExit(f"workspace {args.workspace_id} has no owner")
        owner_id = owner_row[0]

        await session.execute(
            text("SELECT set_config('app.current_workspace_id', :ws, true)"),
            {"ws": args.workspace_id},
        )
        result = await seed_demo_workspace(
            session, workspace_id=args.workspace_id, actor_user_id=owner_id
        )
    print(
        f"ok. workspace={args.workspace_id}\n"
        f"  entities={result.entities_created}+{result.entities_updated}updated "
        f"edges={result.edges_created} "
        f"docs={result.documents_created} episodes={result.episodes_created} "
        f"sessions={result.agent_sessions_created}"
    )


async def _cmd_reset(args: argparse.Namespace) -> None:
    async with session_scope() as session:
        r = await session.execute(
            text(
                "SELECT id::text FROM workspace "
                "WHERE slug = :slug AND deleted_at IS NULL"
            ),
            {"slug": args.workspace_slug},
        )
        row = r.first()
        if not row:
            raise SystemExit(f"workspace slug={args.workspace_slug!r} not found")
        ws_id = row[0]

        owner = await session.execute(
            text(
                "SELECT user_id::text FROM workspace_member "
                "WHERE workspace_id = CAST(:id AS uuid) AND role = 'owner' "
                "LIMIT 1"
            ),
            {"id": ws_id},
        )
        owner_row = owner.first()
        if not owner_row:
            raise SystemExit("no owner found")
        owner_id = owner_row[0]

        # Nuclear wipe of workspace content (not the workspace itself) —
        # entities/edges/docs/episodes cascade off workspace via FKs we
        # don't have, so delete by workspace_id explicitly.
        for table in (
            "agent_tool_call",
            "agent_session",
            "block_entity_ref",
            "block",
            "document",
            "episode",
            "edge",
            "entity_attribute",
            "entity",
            "audit_log",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = CAST(:ws AS uuid)"),
                {"ws": ws_id},
            )

        # Re-seed ontology + demo.
        from app.domain.ontology_seed import seed_workspace as seed_ontology

        await session.execute(
            text("SELECT set_config('app.current_workspace_id', :ws, true)"),
            {"ws": ws_id},
        )
        await seed_ontology(session, ws_id)
        result = await seed_demo_workspace(
            session, workspace_id=ws_id, actor_user_id=owner_id
        )
    print(
        f"ok. reset workspace={ws_id}\n"
        f"  entities={result.entities_created} "
        f"edges={result.edges_created} "
        f"docs={result.documents_created}"
    )


async def _main() -> None:
    configure_logging("INFO")
    args = _mk_parser().parse_args()
    if args.cmd == "create":
        await _cmd_create(args)
    elif args.cmd == "populate":
        await _cmd_populate(args)
    elif args.cmd == "reset":
        await _cmd_reset(args)
    else:
        raise SystemExit(f"unknown command: {args.cmd!r}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(130)
