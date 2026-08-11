---
tags: [aso/log]
status: current
updated: 2026-08-11
---

# Session Log

Append-only. Newest first. One entry per meaningful chunk of work. Index: [[00 Index]].

Keep entries short: **what changed · why · what it unblocks · what to verify.**

---

## 2026-08-11 — Phase 0: knowledge base

**What.** Created this vault (`vault/`) and root `CLAUDE.md`. Branch `worktree-aso-full-build`.

**Why.** Every session was re-deriving the same context from a 1,406-line spec plus 4,100 lines of source. The vault makes the verified findings durable and the [[Roadmap]] explicit.

**Findings recorded.** Seven blocking defects ([[Known Defects]]) found by reading code — most importantly that `create_snapshot()` is never called by the queue, so **historical replay does not actually work** and the system has never run a real benchmark.

**Decisions locked.** [[ADR-001 Harness Choice]] (smolagents before OpenHands), [[ADR-002 Model Selection]] (three free models), [[ADR-003 Free Tier Constraints]] (quota sets the schedule), [[ADR-004 Backend on Host]] (recorded from the earlier eng review).

**Baseline at start.** 77 backend tests passing; 15 of 25 acceptance criteria fully met ([[Acceptance Criteria]]).

**Next.** Phase 1 — Alembic scaffolding, `app/seed.py`, frontend test infra. See [[Roadmap]].

---

## 2026-08-11 — Phase 1: foundations repaired

**What.** Alembic scaffolded, `app/seed.py` added, frontend test stack stood up. Also re-applied the 8000→8005 port change (it was uncommitted in the main checkout, so the worktree branched without it) and fixed the two stale `:8000` doc references.

**Migrations are now the single source of truth.** `env.py` reads `settings.database_url` and reuses `make_engine()` (so it inherits WAL pragmas and data-dir creation). `create_all` removed from `main.py`; `ensure_schema()` runs `upgrade head` at startup so dev/demo/tests need no manual step. Initial migration covers all 14 tables.

**Guard added.** `test_migrations.py::test_no_migration_drift` uses `compare_metadata` to fail if a model changes without a migration — without it, models and migrations diverge silently.

**Bug found while verifying.** `test_retry_failed_run` queried `BenchmarkRun` globally across the shared test DB with no scoping or `ORDER BY`, then asserted on `[-1]`. Passed alone, failed intermittently in the full suite. Now scoped to its own experiment. Recorded as [[Known Defects]] #8.

**Frontend.** vitest + Testing Library + MSW, 7 tests covering api error propagation and Dashboard empty/offline/populated states. `make test-frontend` was a false green (`npm test --if-present` with no test script); it now actually runs.

**Verified.** `make lint` ✅ · `make typecheck` ✅ (mypy 49 files, tsc clean) · `make test` ✅ (79 backend + 7 frontend) · `make demo` ✅ all runs COMPLETED · `make migrate` ✅ · `make seed` ✅ idempotent.

**Next.** Phase 2 — wire the golden path. Fixes [[Known Defects]] #1, #2, #3, the ones that mean historical replay does not actually work.

---

<!-- New entries above this line -->
