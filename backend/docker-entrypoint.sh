#!/bin/sh
# Backend entrypoint: wait for Postgres, then exec CMD.
#
# NOTE: We do NOT run migrations here. On Render, migrations run once via
# the `preDeployCommand: alembic upgrade head` in render.yaml before
# traffic is swapped. In local compose, the `backend-migrate` one-shot
# service runs them once on `docker compose up`. Running migrations inline
# on every container start creates a race on scale-up.

set -e

echo "backend.entrypoint: waiting for postgres…"
# Simple readiness check. Compose's healthcheck also gates us, but this
# guards against races where the socket is up but auth isn't ready yet.
for i in $(seq 1 30); do
  if python -c "
import os, sys
import psycopg2
try:
    psycopg2.connect(os.environ['POSTGRES_SYNC_URL']).close()
except Exception as e:
    sys.exit(1)
" 2>/dev/null; then
    break
  fi
  echo "  postgres not ready (attempt $i/30)…"
  sleep 1
done

echo "backend.entrypoint: launching $*"
exec "$@"
