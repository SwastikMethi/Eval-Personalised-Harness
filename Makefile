UV := uv --directory backend

.PHONY: setup dev backend frontend test test-backend test-frontend lint typecheck migrate seed demo clean-sandboxes

setup:
	cd backend && uv sync
	cd frontend && npm install

dev:
	$(MAKE) -j2 backend frontend

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8005

frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && npm test --if-present -- --run

lint:
	cd backend && uv run ruff check app tests
	cd frontend && npm run lint --if-present

typecheck:
	cd backend && uv run mypy app
	cd frontend && npx tsc --noEmit

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed

demo:
	cd backend && uv run python -m app.demo

clean-sandboxes:
	docker ps -aq --filter "label=aso.run_id" | xargs -r docker rm -f
