---
tags: [aso/status, aso/defect]
status: current
updated: 2026-08-11
---

# Known Defects

Defects found by reading code on 2026-08-11. **Each one blocks a real benchmark run.** Index: [[00 Index]].

**Status: 5 of 8 fixed** (#1, #2, #3 — Phase 2; #7, #8 — Phase 1). Remaining: **#4, #5, #6** — all Phase 3.

Line references are to the state at branch `worktree-aso-full-build` creation; re-grep before trusting them.

---

## 1. The golden path is severed ✅ FIXED (Phase 2, 2026-08-11)

Was: `service.create_snapshot()` — the [[Leakage Prevention]] `git archive`-at-base-commit builder — was called **only** from `api/repos_analysis.py` during baseline validation. The queue never called it, building every agent workspace with `shutil.copytree(config["fixture_path"])` and ignoring `task.base_commit`. Historical replay silently graded the wrong tree.

Now: `queue.py::materialize_workspace()` snapshots at the task's base commit for any task that has one, falling back to `fixture_path` only for fixture-driven demos (which have no history to leak). It raises rather than guessing when neither is available. `_evaluate` rebuilds its own fresh snapshot so grading never sees anything the agent did except the patch.

**Guard:** `tests/test_golden_path.py` asserts the workspace has no solution file, exactly one commit, and no remotes — plus an end-to-end run proving a from-commit task now grades against a snapshot.

---

## 2. Regression detection is dead on real repos ✅ FIXED (Phase 2, 2026-08-11)

Was: nothing wrote `baseline_cases` into experiment config — only readers existed. `BaselineResult` rows never reached a run, so every regression check compared against an empty baseline.

Now: `routes.py::derive_config()` copies the latest `BaselineResult.test_cases` into experiment config at creation time.

---

## 3. Detected commands never reach runs ✅ FIXED (Phase 2, 2026-08-11)

Was: `RepositoryCommand` rows were populated by analysis but the queue fell back to a hardcoded `{"test": "pytest -v"}` — a JS/TS repo would have been graded with pytest.

Now: `derive_config()` supplies install/build/test/lint/typecheck and `test_framework` from the persisted row, with explicit request values still winning so a caller can override.

---

## 4. Cost accounting is inert 🟠

`queue.py:212` calls `issue_run_token()` without `input_price` / `output_price`, so `entry.cost_usd` (`proxy.py:165-168`) never leaves `0.0` and the ceiling at `proxy.py:110` can never fire.

Free models make this $0 anyway — but §14 requires cost recorded even when zero, and this same path is the only guard on a future paid key.

**Fixed in:** Phase 3.

---

## 5. The proxy destroys tool calls 🔴

`proxy.py:180-195` returns a hand-built response containing only `message.content` and a hardcoded `finish_reason: "stop"`. `ChatRequest` (`proxy.py:139`) has no `tools` field, so tool definitions are dropped inbound and tool calls dropped outbound.

**Consequence:** smolagents survives (it parses code from content). **OpenHands cannot work at all.**

**Fixed in:** Phase 3 — prerequisite for Phase 10.

---

## 6. Rate limiting fails the run 🔴

The proxy maps 429 correctly, but `queue.py:175-177` catches *every* exception into `FAILED(HARNESS)`. Nothing ever transitions into `RATE_LIMITED`.

**Consequence:** violates [[Acceptance Criteria]] #24 — and under [[Rate Limits]] (~50 requests/day) this fires constantly, writing spurious `FAILED` rows that corrupt results.

**Fixed in:** Phase 3. **Must land before any real run.**

---

## 7. Broken developer targets ✅ FIXED (Phase 1, 2026-08-11)

Was:

| Target | Failure |
|---|---|
| `make migrate` | `No 'script_location' key found` — `alembic` declared as a dependency but no `alembic/` or `alembic.ini` |
| `make seed` | `No module named app.seed` — only `app/demo.py` existed |
| `make test-frontend` | **False green.** `npm test --if-present` with no test script, no vitest, zero test files → exited 0 while testing nothing |

Now: Alembic scaffolded with `env.py` reading `settings.database_url` and reusing `make_engine()`; initial migration covers all 14 tables; `create_all` removed from `main.py` in favour of `ensure_schema()` so **migrations are the single source of truth**. `app/seed.py` added (idempotent). Frontend has vitest + Testing Library + MSW with 7 real tests.

**Guard against regression:** `tests/test_migrations.py::test_no_migration_drift` fails if a model changes without a matching migration.

---

## 8. `test_retry_failed_run` was order-dependent ✅ FIXED (Phase 1, 2026-08-11)

Found while verifying Phase 1. `tests/test_run_control.py` selected `BenchmarkRun.id` across the **entire shared test database** with no experiment scoping and no `ORDER BY`, then assumed `[-1]` was its own run. Passed in isolation, failed intermittently in the full suite when another test's run happened to sort last.

Now scoped to the test's own experiment via `ExperimentCombination`, matching the pattern `test_cancel_pending_run` already used. Verified stable across three consecutive full-suite runs.

---

## Severity key

🔴 blocks a correct benchmark result · 🟠 blocks correctness on real repos or lies about status

## Related

- [[Implemented]] · [[Spec Gaps]] · [[Roadmap]] · [[Acceptance Criteria]]
