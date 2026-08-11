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

## 2026-08-11 — Phase 2: golden path wired

**What.** `queue.py::materialize_workspace()` now builds the agent workspace from `create_snapshot(repo, task.base_commit, dest)` instead of copying `fixture_path`. `_evaluate` rebuilds its own fresh snapshot. `routes.py::derive_config()` feeds real commands and baseline cases into experiment config at creation.

**Why it mattered.** This is the defect that meant **the system had never actually run a historical replay** — tasks carried a `base_commit` the runs ignored. Fixes [[Known Defects]] #1, #2, #3 and [[Acceptance Criteria]] #10, #11.

**Design note.** `mkdtemp` now creates a *parent*; the workspace is a child that must not pre-exist, because `create_snapshot` deliberately refuses to write into a live directory. Fixture fallback is kept for demos, and a task with neither base commit nor fixture raises rather than grading the wrong tree.

**Verified.** 6 new tests in `test_golden_path.py`: no solution file in the workspace, exactly one commit, no remotes, fixture fallback, explicit refusal, config derivation, and an end-to-end from-commit run reaching COMPLETED with `apply.ok` true. That last one would have failed before — the old `_evaluate` returned `no_evaluation_configured` and wrote no result row whenever `fixture_path` was absent, which is exactly what a real historical task looks like.

**Suite.** 85 backend (+6) and 7 frontend tests pass; lint, typecheck, demo green.

**Next.** Phase 3 — proxy hardening. `RATE_LIMITED` handling is the gate before any real model run.

---

## 2026-08-11 — Phase 3: proxy hardened for quota and tool calls

**What.** Fixes [[Known Defects]] #4, #5, #6 — the last three blockers before a real model run.

**Rate limiting.** The proxy now records `rate_limited` on the run token, so the orchestrator tells "provider throttled us" apart from "the harness broke" without parsing error strings. A throttled run goes `RUNNING → RATE_LIMITED` with a **persisted** `retry_after` (new column + migration), escalating 30s → 120s → 600s, and `_release_rate_limited()` returns it to `PENDING` on the next claim. Persisting the deadline is what lets a parked run survive a restart — at ~50 requests/day this is the ordinary path, not an edge case.

**Tool calls.** `CompletionResult` carries the provider's `message` and real `finish_reason`; the proxy forwards them instead of rebuilding `{"role","content"}` with a hardcoded `"stop"`. `ChatRequest` accepts `tools`/`tool_choice`/`response_format` and the provider passes them upstream. `content=None` on a tool-calling reply no longer reads as a malformed response. Unblocks OpenHands.

**Cost.** `_model_prices()` reads per-token prices from the pinned `ModelSnapshot`, so `cost_usd` accrues and the spend ceiling can actually fire. $0.00 on free models, but recorded, per §14.

**Quota visibility.** `max_model_requests` now defaults to **8** ([[ADR-003 Free Tier Constraints]]), and per-run usage is written into `run.result` so burn is visible before it runs out.

**Bug found while testing.** The test database was migrated only as a *side effect* of some test calling `create_app()`, so a module touching the DB directly passed or failed by collection order. Now an autouse session fixture runs `ensure_schema()` up front. Recorded as [[Known Defects]] #9.

**Verified.** 5 new tests: 429 flags the run, cost accrues until the ceiling fires, tool definitions reach the provider and `tool_calls` return with `finish_reason: "tool_calls"`, parked-then-released backoff, and escalating delays. Suite 90 backend + 7 frontend; lint, typecheck, demo green.

**Next.** Phase 4 — smolagents harness, then Milestone A.

---

<!-- New entries above this line -->
