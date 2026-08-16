---
tags: [aso/reference]
status: current
updated: 2026-08-11
---

# Make Targets

Verified 2026-08-11. Index: [[00 Index]].

| Target | What it does | Works? |
|---|---|---|
| `make setup` | `uv sync` + `npm install` | ✅ |
| `make dev` | backend :8005 + frontend :3000 (parallel) | ✅ |
| `make backend` | uvicorn `--reload --port 8005` | ✅ |
| `make frontend` | `npm run dev` | ✅ |
| `make test` | backend + frontend tests | ✅ |
| `make test-backend` | `pytest` — **79 pass in ~10s** | ✅ |
| `make test-frontend` | `vitest --run` — **7 pass in ~3.5s** | ✅ |
| `make lint` | ruff + oxlint | ✅ |
| `make typecheck` | mypy (49 files) + `tsc --noEmit` | ✅ |
| `make migrate` | `alembic upgrade head` | ✅ |
| `make seed` | `python -m app.seed` — idempotent | ✅ |
| `make demo` | full fake experiment, zero API cost | ✅ |
| `make clean-sandboxes` | remove orphaned containers | ✅ |

All green as of Phase 1 (2026-08-11). Previously `migrate` and `seed` crashed and `test-frontend` was a false green — see [[Known Defects]] #7.

## Migrations

Schema comes **only** from Alembic; there is no `create_all`. `app/db/engine.py::ensure_schema()` runs `upgrade head` at app startup, so `make dev`, `make demo`, and the test suite all work without a manual step.

```sh
cd backend
uv run alembic revision --autogenerate -m "what changed"   # after editing models
uv run alembic upgrade head
uv run alembic current
```

`tests/test_migrations.py::test_no_migration_drift` fails if models and migrations diverge.

> **Existing databases:** a `data/aso.db` created before Alembic was introduced already has the tables but no `alembic_version`, so `upgrade head` will fail on "table already exists". Stamp it once: `uv run alembic stamp head`.

## Prerequisites

- [uv](https://docs.astral.sh/uv/), Node 20+, Docker, macOS/Linux
- `cp .env.example .env` and add `OPENROUTER_API_KEY`
- Sandbox image: `make sandbox-image` → `aso-sandbox-python:dev`, from
  `sandbox-images/python/Dockerfile`

> **Rebuild after editing that Dockerfile.** Nothing does it for you, and a stale
> image surfaces as `command not found` inside a container rather than as
> anything that points at the image. It now carries `make`, `build-essential`
> and `uv` as well as git and Node — see [[Sandbox]].

## Per-phase verification loop (§29)

```sh
make lint && make typecheck && make test
make demo          # must stay green — fake harness, zero quota
```

Then update [[Acceptance Criteria]] and append to [[Session Log]].

## Related

- [[Codebase Map]] · [[ADR-004 Backend on Host]] · [[Known Defects]]
