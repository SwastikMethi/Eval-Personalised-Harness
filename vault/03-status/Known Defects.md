---
tags: [aso/status, aso/defect]
status: current
updated: 2026-08-11
---

# Known Defects

Defects found by reading code on 2026-08-11. **Each one blocks a real benchmark run.** Index: [[00 Index]].

## 15. GitHub clones raced themselves ✅ FIXED (2026-08-11)

**The first defect caused by my own change.** `clone_github` did `shutil.rmtree(dest)` and re-cloned on *every* call, and `_repo_root()` calls it for every GitHub-sourced request. Backgrounding the baseline (wizard rework) meant the baseline and the commits query ran concurrently — so one deleted the working tree the other was running `git log` inside, and a perfectly good GitHub repo reported **zero commits**. Local repos were immune because `register_local` only validates a path.

Re-cloning was also wrong on its own terms: silently re-fetching moves history under a running experiment when a benchmark should measure a fixed snapshot.

Now clone-once/reuse-after, keyed on a matching `origin`, serialized by a per-repo lock. Measured after the fix: first analyze 34.8s (clone), subsequent commits **0.4s** (reuse).

Compounded by a UI defect: `commits.isError` was never rendered, so a failed clone looked identical to "this repo has no commits". Both now covered by tests.

---

## 16. Install and tests ran under different interpreters ✅ FIXED (2026-08-12)

Baselining a repo showed **INSTALL pass · TEST exit 2 · BASELINE TESTS 0**. The captured output had `pip` writing to `…/miniforge/base/lib/python3.13/site-packages` while pytest ran under `…/uv/python/cpython-3.12.13`. Install succeeded at installing nothing the tests could see, then the tests failed on a dependency that had just been "installed".

Confirmed at the source: the uv-created venv contains `pytest` but **no `pip`**, so `pytest` resolved inside the venv (3.12) while `pip` fell through `PATH` to miniforge (3.13). Not fixable by editing commands, and silent — the contradiction only surfaced because someone read the raw output.

Fixed by running baseline and evaluation **in a container** (which `sandboxes/exec.py` had always described as the intended shape), with dependencies installed once per repo into a prepared image. Also a security improvement: evaluation executes the agent's patch, which previously ran on the host.

Two things this exposed about the UI: `exit 2` alone is undiagnosable, so failing step output is now rendered in the Setup panel; and diagnosing it required opening SQLite by hand, which is not a thing a user should ever do.

---

**Status: all 16 fixed.** #1–#3 Phase 2 · #4–#6 Phase 3 · #7–#8 Phase 1 · #9 Phase 3 · **#10–#14 found by attempting the first real model run**. Kept as a record of what was wrong and what guards it now.

> Defects #10–#14 are the important ones: each alone made a sandboxed benchmark impossible, and none was visible from the test suite, because nothing had ever executed a real run.

---

## 10. Sealing killed the proxy path 🔴 ✅ FIXED (2026-08-11)

A container on an `internal: true` network has no default route **at all** — not to the internet and not to the host gateway. So `host.docker.internal` died along with egress, contradicting what [[Sandbox]] and `docs/architecture.md` both claimed.

Measured: proxy answered `200` before `seal()`, unreachable after.

**Why it stayed invisible:** `seal()` only verified that egress was dead, never that the proxy was alive. So every sandboxed run made **zero model requests and reported `COMPLETED`** — the worst possible failure mode.

Now: a per-run relay container straddles both networks; `seal()` fails closed in both directions. See [[Sandbox]].

---

## 11. mini-swe-agent addressed containers by task_id 🔴 ✅ FIXED

`prepare()` passed `request.task_id` to the sandbox manager, which keys containers by **run_id** — so every sandboxed run died with `KeyError` during PREPARING. This harness could never have started in a sandbox. Guarded by `tests/test_mini_swe_agent.py`.

---

## 12. mini-swe-agent demanded interactive setup 🟠 ✅ FIXED

Without `MSWEA_CONFIGURED` the CLI drops into a first-run wizard asking for a model and API key, which in a non-tty container simply fails. Set alongside `MSWEA_SILENT_STARTUP`.

---

## 13. litellm cost lookup killed every run 🔴 ✅ FIXED

mini **re-raises** when litellm cannot price a model, so the run died right after its first successful completion. litellm has no pricing for a model served through our proxy. Fixed via the documented `LITELLM_MODEL_REGISTRY_PATH` hook; zero is the true cost for the pinned free variants, and the proxy's `ModelRequestMetric` rows stay authoritative.

---

## 14. The real provider was never installed 🔴 ✅ FIXED

`proxy.set_provider()` was never called with `OpenRouterProvider`, so the proxy kept its `FakeProvider` default forever — a "real" run got canned completions. Compounded by `env_file=".env"` resolving against the process CWD, so `make backend` (which runs from `backend/`) never loaded the repo-root `.env` and the API key never arrived.

Fixing the second exposed a third: with the root `.env` loading, the **test suite** picked up the real key and started making live API calls. `conftest.py` now pins `OPENROUTER_API_KEY` empty so tests are hermetic by construction and can never spend quota.

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

## 4. Cost accounting is inert ✅ FIXED (Phase 3, 2026-08-11)

Was: `issue_run_token()` was called without `input_price` / `output_price`, so `cost_usd` never left `0.0` and the spend ceiling could never fire no matter how much was spent.

Now: `queue.py::_model_prices()` reads per-token prices from the pinned `ModelSnapshot` and passes them through. Free models still record $0.00, as §14 requires.

---

## 5. The proxy destroys tool calls ✅ FIXED (Phase 3, 2026-08-11)

Was: the proxy returned a hand-built response containing only `message.content` with a hardcoded `finish_reason: "stop"`, and `ChatRequest` had no `tools` field — so tool definitions were dropped inbound and tool calls dropped outbound. A harness would believe the model answered when it had actually asked to call a tool.

Now: `ChatRequest` accepts `tools`, `tool_choice`, `response_format`; the provider forwards them; `CompletionResult` carries the provider's `message` and real `finish_reason`, and the proxy returns them untouched. `content=None` on a tool-calling reply is handled rather than treated as malformed.

**Unblocks:** OpenHands (Phase 10).

---

## 6. Rate limiting fails the run ✅ FIXED (Phase 3, 2026-08-11)

Was: the proxy mapped 429 correctly but the queue caught *every* exception into `FAILED(HARNESS)`. Nothing ever entered `RATE_LIMITED`, so under [[Rate Limits]] (~50 requests/day) ordinary throttling both lost the run and poisoned the reliability statistics with a failure the agent never caused.

Now: the proxy records `rate_limited` on the run token, so the orchestrator distinguishes "provider throttled us" from "the harness broke" without parsing error strings. A throttled run goes `RUNNING → RATE_LIMITED` with a **persisted** `retry_after` deadline (escalating 30s → 120s → 600s), and `_release_rate_limited()` returns it to `PENDING` when the deadline passes. Persisting the deadline means a parked run survives a restart.

**Satisfies:** [[Acceptance Criteria]] #24.

---

## 9. Test schema depended on collection order ✅ FIXED (Phase 3, 2026-08-11)

Found while adding Phase 3 tests. The test database was only migrated as a *side effect* of some test calling `create_app()`, so a module touching the DB directly passed or failed depending on which tests ran first. Now an autouse session fixture in `conftest.py` runs `ensure_schema()` up front — which also means the suite exercises the real migration path.

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
