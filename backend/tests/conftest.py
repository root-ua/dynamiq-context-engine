"""Pytest fixtures.

These tests require a live Postgres with our extensions. The easiest path is:

    docker compose up -d postgres
    cd backend
    POSTGRES_URL=postgresql+asyncpg://memory:memory@localhost:5432/memory \
    POSTGRES_SYNC_URL=postgresql://memory:memory@localhost:5432/memory \
    JWT_SECRET=test \
    pytest

RLS hygiene note: the default ``memory`` Postgres role used by tests is
a superuser with ``BYPASSRLS=t``, so RLS policies in migrations do NOT
filter rows during tests. The application's ACL is application-layer
(``app/auth/acl.py`` builds explicit SQL clauses), so this does not
make tests theatre — but it does mean app code that *implicitly* relies
on RLS will silently leak across workspaces in tests. Per-scenario
fixtures that depend on RLS enforcement should explicitly set
``app.current_workspace_id`` AND scope their SELECTs.
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("POSTGRES_URL", "postgresql+asyncpg://memory:memory@localhost:5432/memory")
os.environ.setdefault("POSTGRES_SYNC_URL", "postgresql://memory:memory@localhost:5432/memory")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.db.session import session_scope
from app.domain import entity as entity_mod
from app.domain.workspace import create_workspace

# Expose scenario fixtures globally so K + L tests can request them
# without per-file imports.
from tests.fixtures.enterprise import enterprise_workspace  # noqa: F401
from tests.fixtures.reranker import stub_reranker  # noqa: F401


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def workspace():
    """Creates a fresh workspace (+ built-in ontology) per test."""
    user_id = str(uuid4())
    # Create a test user directly.
    async with session_scope(user_id=user_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO app_user (id, email, password_hash, name)
                VALUES (:id, :email, :hash, :name)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": user_id,
                "email": f"test-{user_id}@example.com",
                "hash": "x",
                "name": "Test User",
            },
        )

    slug = f"t-{uuid4().hex[:8]}"
    async with session_scope(user_id=user_id) as session:
        ws = await create_workspace(
            session, owner_user_id=user_id, slug=slug, name=f"Test {slug}"
        )

    yield {"workspace_id": ws.id, "user_id": user_id, "slug": slug}

    # Cleanup.
    async with session_scope() as session:
        await session.execute(
            text("DELETE FROM workspace WHERE id = :id"), {"id": ws.id}
        )


@pytest_asyncio.fixture
async def two_people(workspace):
    ws_id = workspace["workspace_id"]
    async with session_scope(workspace_id=ws_id, user_id=workspace["user_id"]) as session:
        alice = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="person",
            canonical="Alice", aliases=["A. Smith"], embed=False,
        )
        acme = await entity_mod.create(
            session, workspace_id=ws_id, type_ref="organization",
            canonical="Acme", embed=False,
        )
    return {"alice": alice.id, "acme": acme.id, **workspace}
