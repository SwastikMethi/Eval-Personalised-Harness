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
| `make test` | backend + frontend tests | ⚠️ backend only |
| `make test-backend` | `pytest` — **77 pass in ~9s** | ✅ |
| `make test-frontend` | `npm test --if-present` | ❌ **false green** |
| `make lint` | ruff + oxlint | ✅ |
| `make typecheck` | mypy + `tsc --noEmit` | ✅ |
| `make migrate` | `alembic upgrade head` | ❌ **fails** |
| `make seed` | `python -m app.seed` | ❌ **fails** |
| `make demo` | full fake experiment, zero API cost | ✅ |
| `make clean-sandboxes` | remove orphaned containers | ✅ |

## The three broken ones

```
make migrate → FAILED: No 'script_location' key found in configuration.
make seed    → No module named app.seed
make test-frontend → exits 0 having run nothing
```

`alembic` is a declared dependency in `pyproject.toml` but there is no `alembic/` directory or `alembic.ini`. `app/seed.py` does not exist (only `app/demo.py`). The frontend has no `test` script, no vitest, and zero test files — `--if-present` silently succeeds.

All three fixed in [[Roadmap]] Phase 1. Tracked as [[Known Defects]] #7.

## Prerequisites

- [uv](https://docs.astral.sh/uv/), Node 20+, Docker, macOS/Linux
- `cp .env.example .env` and add `OPENROUTER_API_KEY`
- Sandbox image: `aso-sandbox-python:dev` (built from `sandbox-images/python/Dockerfile`)

## Per-phase verification loop (§29)

```sh
make lint && make typecheck && make test
make demo          # must stay green — fake harness, zero quota
```

Then update [[Acceptance Criteria]] and append to [[Session Log]].

## Related

- [[Codebase Map]] · [[ADR-004 Backend on Host]] · [[Known Defects]]
