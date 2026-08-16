UV := uv --directory backend

.PHONY: setup sandbox-image dev backend frontend test test-backend test-frontend lint typecheck migrate seed demo clean-sandboxes

setup:
	cd backend && uv sync
	cd frontend && npm install

# The image every sandboxed run and every baseline starts from. Rebuild after
# editing sandbox-images/python/Dockerfile — nothing does it automatically, and
# a stale image shows up as "command not found" inside a container.
sandbox-image:
	docker build -t aso-sandbox-python:dev sandbox-images/python

dev:
	$(MAKE) -j2 backend frontend

# --host 0.0.0.0 is required, not cosmetic: sandboxed agents reach the model
# proxy through a relay container, and a server bound to uvicorn's default
# 127.0.0.1 is unreachable from Docker's host gateway. Every run then makes
# zero model requests and fails with an opaque connection error.
backend:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8005

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
	docker network ls -q --filter "label=aso.run_id" | xargs -r docker network rm
	@# Prepared images accumulate one per repo per manifest revision.
	docker images -q "aso-prepared:*" | xargs -r docker rmi -f
