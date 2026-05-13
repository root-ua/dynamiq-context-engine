.PHONY: up down logs seed test test-live test-scenario lint typecheck fmt clean

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=100

seed:
	docker compose exec backend python -m app.scripts.seed_demo create \
	  --owner-email demo@example.com

test:
	cd backend && uv run --extra dev pytest -m "not live_llm"

test-scenario:
	cd backend && uv run --extra dev pytest -m scenario

test-live:
	cd backend && uv run --extra dev pytest -m live_llm

lint:
	cd backend && uv run --extra dev ruff check app/ tests/
	cd web && pnpm lint

typecheck:
	cd backend && uv run --extra dev mypy app/
	cd web && pnpm typecheck

fmt:
	cd backend && uv run --extra dev ruff format app/ tests/
	cd web && pnpm format

clean:
	rm -rf backend/.venv backend/.pytest_cache web/node_modules web/.next
