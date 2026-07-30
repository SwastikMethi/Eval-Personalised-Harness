# Agent Stack Optimizer

Benchmark combinations of coding-agent harness × open-weight model (via OpenRouter) × config against tasks from **your own repository**, and get best-quality / best-reliability / best-efficiency / best-balanced recommendations. Local, single-user MVP.

Spec: `generationDoc.md`. Plan: see `docs/implementation-plan.md` (mirrors the reviewed plan).

## Status

- ✅ **Stage 1 — Foundation + walking skeleton**: FastAPI backend (uv, Python 3.12), SQLite (WAL), state-machine queue, run-scoped model proxy with per-run tokens, FakeHarness/FakeProvider exercising the real proxy protocol, React+MUI dashboard shell. `make demo` runs a full fake experiment end-to-end.
- ⬜ Stage 2 — Repository analysis + baseline validation
- ⬜ Stage 3 — OpenRouter provider + live model proxy
- ⬜ Stage 4 — Docker sandbox (two-phase network) + mini-SWE-agent
- ⬜ Stage 5 — Tasks, hidden tests, evaluators
- ⬜ Stage 6 — Results, recommendations, full UI
- ⬜ Stage 7 — Fixture polish, docs, hardening

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, Docker (Stage 4+), macOS/Linux.

```sh
make setup        # backend deps (uv sync) + frontend deps (npm install)
cp .env.example .env   # add your OPENROUTER_API_KEY (Stage 3+)
make dev          # backend :8000 (native host process) + frontend :3000
make test         # backend pytest + frontend tests
make demo         # end-to-end fake experiment, zero API cost
```

The backend runs natively on the host (not in a container) so it can manage sibling sandbox containers without socket mounts or path translation. See `TODOS.md` for the Compose packaging follow-up.

## Layout

```
backend/    FastAPI app: api/, core/, db/, models/, providers/, harnesses/, orchestration/
frontend/   React + TS + Vite + MUI dashboard
fixtures/   python-bug-repo demo fixture
data/       SQLite DB + run artifacts (gitignored)
```
