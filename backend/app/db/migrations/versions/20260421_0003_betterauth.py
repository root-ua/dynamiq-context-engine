"""betterauth: user/session/account/verification tables

Revision ID: 20260421_0003
Revises: 20260421_0002
Create Date: 2026-04-21

BetterAuth (the Next.js auth layer) needs its own four tables. We create
them here instead of via `@better-auth/cli migrate` so a fresh
`docker compose up` lands a working stack in one step.

Notes:
- BetterAuth uses camelCase identifiers; they must be double-quoted in
  Postgres or they'll be folded to lowercase.
- `id` is `text DEFAULT gen_random_uuid()::text`. BetterAuth's Kysely
  adapter delegates id generation to the DB when `advanced.database.
  generateId === "uuid"` AND the adapter reports `supportsUUIDs`. Our
  web config uses that mode; this default satisfies the contract.
- FKs that point at `app_user(id)` (the memory-platform user table) all
  use the BetterAuth user's uuid value, so the two user tables stay in
  lockstep. The mirror row is written by a BetterAuth `databaseHooks.
  user.create.after` hook; see `web/lib/auth.ts`.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260421_0003"
down_revision: str | None = "20260421_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "user" (
          id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
          name text NOT NULL,
          email text NOT NULL UNIQUE,
          "emailVerified" boolean NOT NULL,
          image text,
          "createdAt" timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          "updatedAt" timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "session" (
          id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
          "expiresAt" timestamptz NOT NULL,
          token text NOT NULL UNIQUE,
          "createdAt" timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          "updatedAt" timestamptz NOT NULL,
          "ipAddress" text,
          "userAgent" text,
          "userId" text NOT NULL REFERENCES "user"(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS "session_userId_idx" ON "session"("userId");
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "account" (
          id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
          "accountId" text NOT NULL,
          "providerId" text NOT NULL,
          "userId" text NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
          "accessToken" text,
          "refreshToken" text,
          "idToken" text,
          "accessTokenExpiresAt" timestamptz,
          "refreshTokenExpiresAt" timestamptz,
          scope text,
          password text,
          "createdAt" timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          "updatedAt" timestamptz NOT NULL
        );
        CREATE INDEX IF NOT EXISTS "account_userId_idx" ON "account"("userId");
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS verification (
          id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
          identifier text NOT NULL,
          value text NOT NULL,
          "expiresAt" timestamptz NOT NULL,
          "createdAt" timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          "updatedAt" timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS verification_identifier_idx
          ON verification(identifier);
        """
    )


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS verification CASCADE')
    op.execute('DROP TABLE IF EXISTS "account" CASCADE')
    op.execute('DROP TABLE IF EXISTS "session" CASCADE')
    op.execute('DROP TABLE IF EXISTS "user" CASCADE')
