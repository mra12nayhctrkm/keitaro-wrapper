.PHONY: install migrate dev backend frontend build start test check

install:          ## install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && npm ci

migrate:          ## apply database migrations
	cd backend && uv run alembic upgrade head

backend:          ## API on :8000 with auto-reload
	cd backend && uv run uvicorn app.main:create_app --factory --reload --port 8000

frontend:         ## UI on :5173 with hot reload (proxies /api to :8000)
	cd frontend && npm run dev

dev: migrate      ## backend + frontend in one terminal
	$(MAKE) -j2 backend frontend

build:            ## production frontend build, served by the backend
	cd frontend && npm run build

start: migrate build  ## everything on http://localhost:8000
	cd backend && uv run uvicorn app.main:create_app --factory --port 8000

test:             ## all tests
	cd backend && uv run pytest
	cd frontend && npm test

check:            ## lint, types, tests (what CI runs)
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov
	cd frontend && npm run lint && npm run typecheck && npm test
