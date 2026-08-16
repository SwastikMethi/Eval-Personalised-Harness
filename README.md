# Agent Stack Optimizer

Benchmark combinations of coding-agent harness × open-weight model (via OpenRouter) × config against tasks from **your own repository**, and get best-quality / best-reliability / best-efficiency / best-balanced recommendations. Local, single-user MVP.

Spec: `generationDoc.md`. Plan: see `docs/implementation-plan.md` (mirrors the reviewed plan).

## Status

- ✅ **Stage 1 — Foundation + walking skeleton**: FastAPI backend (uv, Python 3.12), SQLite (WAL), state-machine queue, run-scoped model proxy with per-run tokens, FakeHarness/FakeProvider exercising the real proxy protocol, React+MUI dashboard shell.
- ✅ **Stage 2 — Repository analysis + baseline**: Python/JS-TS detectors, editable commands, leakage-proof snapshots, per-test-case baseline results, submodule/LFS rejection.
- ✅ **Stage 3 — OpenRouter provider + hardened proxy**: exact free-variant pinning, error normalization, routing-metadata recording, request/token/spend budgets, token expiry+renewal, per-request metrics.
- ✅ **Stage 4 — Docker sandbox + mini-SWE-agent**: two-phase network (PREP → sealed internal-only, fail-closed probe), crash reconciliation, cancel/retry/pause/resume, harness in-container (pinned 1.14.0).
- ✅ **Stage 5 — Tasks + evaluation**: commit replay, conservative hidden-test extraction with approval, fresh-snapshot evaluation (prohibited-file gate, identity-based regressions, INSUFFICIENT_EVALUATION_SIGNAL).
- ✅ **Stage 6 — Results + recommendations**: reliability aggregation, eligibility rules, weighted scoring (fast-but-wrong never wins), Pareto frontiers, 4 recommendation cards, results UI with live progress.
- ✅ **Stage 7 — Docs + verification**: `docs/architecture.md` (leakage, scoring, security limits, extension points).

Next pass: OpenHands + smolagents adapters, PR replay, container-executed evaluation, onboarding wizard UI, Playwright smoke test, Compose packaging (TODOS.md).

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, Docker (Stage 4+), macOS/Linux.

```sh
make setup        # backend deps (uv sync) + frontend deps (npm install)
cp .env.example .env   # add your OPENROUTER_API_KEY (Stage 3+)
make dev          # backend :8005 (native host process) + frontend :3000
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
