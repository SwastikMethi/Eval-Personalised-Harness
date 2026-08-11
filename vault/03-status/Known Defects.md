---
tags: [aso/status, aso/defect]
status: current
updated: 2026-08-11
---

# Known Defects

Defects found by reading code on 2026-08-11. **Each one blocks a real benchmark run.** Index: [[00 Index]].

**Status: 2 of 8 fixed** (#7, #8 — Phase 1). Remaining: #1–#6.

Line references are to the state at branch `worktree-aso-full-build` creation; re-grep before trusting them.

---

## 1. The golden path is severed 🔴

`service.create_snapshot()` — the [[Leakage Prevention]] `git archive`-at-base-commit builder — is called **only** from `api/repos_analysis.py:157` during baseline validation. The queue never calls it.

`orchestration/queue.py:208` builds every agent workspace with:

```python
fixture = config.get("fixture_path")
if fixture:
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)
```

**Consequence:** historical replay does not actually work. A task carries `base_commit`, but the run ignores it and copies a raw directory.

**Blocks:** [[Acceptance Criteria]] #10, #11. **Fixed in:** [[Roadmap]] Phase 2.

---

## 2. Regression detection is dead on real repos 🔴

Nothing writes `baseline_cases` into experiment config — grep finds only *readers* (`queue.py:329`), no producer. `BaselineResult` rows exist but never reach a run.

**Consequence:** every regression check compares against an empty baseline, so regressions are invisible.

**Fixed in:** Phase 2.

---

## 3. Detected commands never reach runs 🟠

`RepositoryCommand` rows are populated by analysis, but `queue.py:327` falls back to a hardcoded `{"test": "pytest -v"}`.

**Consequence:** a JS/TS repo would be graded with pytest.

**Fixed in:** Phase 2.

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
