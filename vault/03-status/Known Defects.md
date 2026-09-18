---
tags: [aso/status, aso/defect]
status: current
updated: 2026-08-18
---

# Known Defects

Defects found by reading code on 2026-08-11. **Each one blocks a real benchmark run.** Index: [[00 Index]].

## 18. Preflight's one-token probe rejects reasoning models 🔴 OPEN (2026-08-14)

`providers/preflight.py::probe` sends `max_tokens=1`. A reasoning model spends its output budget on reasoning before emitting any text, and OpenAI answers with a **400**, not a 200 with `finish_reason="length"`:

```
gpt-5.6-sol  ok=False  "Could not finish the message because max_tokens or model
                        output limit was reached. Please try again with higher max_tokens."
gpt-4.1      ok=True
```

A 400 is non-retryable, so `probe` marks the model **permanently unusable** and deletes the combination from the experiment. The model is fine — the probe is too small. Same class of mistake as the timeout case the function already guards against ("slow is not broken"): availability is being inferred from a limit of ours, not the vendor's.

Raising the probe budget (16 was enough for every gpt-5 model measured) is a one-line change, but it applies to **every** provider's preflight and so costs marginally more quota per probe under [[ADR-003 Free Tier Constraints]]. Left open pending that call.

**Confirmed again, elsewhere, 2026-08-14.** Test generation asked gpt-5.6-sol for a ~40-line pytest file with `max_tokens=1600` and got an **empty body** — reasoning consumed the whole budget before a character was emitted. Raised to 6000 in `tasks/generate_tests.py` and the same commit then generated a verified test on the first attempt. So this is not a quirk of the 1-token probe: any caller sizing `max_tokens` for the visible output alone will starve a reasoning model. Worth auditing every literal `max_tokens` when this defect is finally closed.

Does **not** affect repository analysis, which asks for 1200 tokens.

**Tested against the judge and cleared, 2026-09-07.** The grading path was the obvious next suspect — `judge_answer` sent `max_tokens=4000`, the largest prompt we build, to a reasoning model. Measured rather than assumed: the same answer scores **0.83 at both 4,000 and 12,000**, four samples each, zero spread, responses ~2,200 characters. The judge is not being starved. The ceiling was raised to 12,000 regardless, as cheap insurance on a real class of failure — unused budget is not billed — but it fixed nothing observed, and `judge.py` says so where the constant is defined.

---

## 17. OpenAI provider sent two parameters the gpt-5 family rejects 🔴 ✅ FIXED (2026-08-14)

Repository analysis against `ANALYZER_PROVIDER=openai` failed before reaching the model. Two independent vendor mismatches, both measured against the live API rather than read from docs:

| parameter | gpt-5.6-sol / gpt-5.5 | gpt-4.1 |
|---|---|---|
| `max_tokens` | 400 — "use `max_completion_tokens` instead" | accepted |
| `temperature=0.0` | 400 — "only the default (1) value is supported" | accepted |

Callers were blameless: `suggest_setup` asks for `max_tokens=1200, temperature=0.0` and should keep asking for exactly that. Translating a request into a vendor's dialect is the provider's job.

Now: `OpenAICompatibleProvider.max_tokens_field` names the wire spelling per vendor (NIM keeps `max_tokens`, OpenAI sends `max_completion_tokens`), and `OpenAIProvider.complete` drops `temperature` for the families that reject it. Dropped rather than coerced to 1.0 — the vendor default *is* 1, so omitting records "could not honour" instead of implying the caller asked for it.

**The cost, stated plainly:** gpt-5.x analysis is **not reproducible**. The determinism knob does not exist on those models. Pin `ANALYZER_MODEL=gpt-4.1` when a repeatable analysis matters more than the stronger model.

**Guard against regression:** `tests/test_openai_provider.py` asserts both spellings on the wire and that gpt-4.x keeps its `temperature=0.0`.

---

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

## 19. A monorepo's dependencies never reached the image 🔴 ✅ FIXED (2026-08-17)

`Eval-Personalised-Harness` failed its baseline with `make: not found`. The missing `make` was the visible defect and the least of three; the build log said `transferring context: 138B`, which is the generated Dockerfile and nothing else.

Manifests were discovered **root-only** (`root / "pyproject.toml"`) and copied **flattened** to their basename. A repo keeping `backend/pyproject.toml` and `frontend/package.json` therefore contributed nothing to the build context, and `cd backend && uv sync` could never have found its file even with `make` present. `detectors.py` shares the root-only assumption, which is why the same repo detects as "python" with no package manager.

Now `sandboxes/environment.py` searches one directory deep, preserves paths, and resolves system packages from a fixed allowlist. `make`, `build-essential` and `uv` joined the base image (`make sandbox-image`).

## 20. The prepared image cached work the mount then erased 🟠 ✅ FIXED (2026-08-17)

Found while verifying #19. Every container bind-mounts the host workspace over `/workspace`, so anything the image wrote *there* is hidden the instant the container starts. `pip install` reaches site-packages and survives — that is the case the cache was designed for — but `uv sync` writes `.venv` and `npm install` writes `node_modules` inside the project, and both are erased.

So for uv and npm repos the cache was not merely useless: a full `make setup` build measured **over ten minutes** of uv and npm work, discarded on every cache miss, before a test step that then could not see any of it. Those installs now skip the image and run in-container, where the result persists into the test step.

## 21. A failed install reported the repo unbenchmarkable 🟠 ✅ FIXED (2026-08-17)

`run_baseline` returned `benchmarkable=False` the moment the prebuilt install failed, without attempting the suite. That reported `make: not found` — a gap in **our** sandbox image — as "this repository cannot be scored", and threw away stdlib-only or vendored repos whose tests pass with no install at all.

Now `missing_tool()` names the executable from the exit-127 output, the step carries a `diagnosis` the UI renders, and `warn` is set instead of halting. A suite that genuinely cannot run still yields no signal, so this degrades rather than papers over.

## 22. The relay's port was hardcoded while the agent's was configurable 🔴 ✅ FIXED (2026-08-17)

`sandboxes/manager.py` set `PROXY_PORT = 8005` as a literal, but `queue.py` built the agent's proxy URL from `settings.backend_port`. The relay therefore listened on 8005 and forwarded to 8005 no matter what the backend was actually bound to.

A backend on any other port hands the sealed agent a URL nothing is listening on. Worse is the case measured here: a *second* backend already held 8005, so the agent's requests reached that server instead, which had never issued the run's token and answered `401 invalid or expired run token`. The run failed in 32 s having made zero model requests, and the error was categorised `harness`.

`PROXY_PORT` now derives from `settings.backend_port`, so the relay's listen port, its destination, and the agent's URL cannot disagree.

## 23. The proxy documented a retry it did not have 🔴 ✅ FIXED (2026-08-17)

The refund comment in `api/proxy.py` ended "…and provider errors are retried a capped number of times." No retry existed anywhere — not in the proxy, not in `openai_compat`, not in `openrouter`. `provider_error_retryable` was recorded on the run token and never read.

This is only invisible while providers behave. Measured against `nvidia/nemotron-3-ultra-550b-a55b`: a sub-second **503** on roughly one request in seven, reproduced with a plain direct call carrying no proxy and no harness, so it is the provider's. Neither harness retries, so the first 503 ends the run — two consecutive runs died at request 8 and request 2 — and at that rate a twenty-step run has almost no chance of finishing. The failure was then booked against the harness, corrupting the one statistic this product exists to produce.

Now capped at 2 retries with 1 s / 3 s backoff, and only for errors the provider itself flagged retryable. `RATE_LIMITED` is deliberately excluded: it keeps its own 429 path so the queue can back off, and retrying inline would spend quota fighting a limit that needs waiting out. Every attempt still writes its own `ModelRequestMetric` row, including ones a retry recovers — hiding them would understate exactly the provider flakiness being measured. The refund moved to the give-up path so a call a retry rescues still counts as the one request the agent made.

## 24. A grouped run showed one task's grade, and the wrong one 🔴 ✅ FIXED (2026-08-18)

A run answers every task that shared its snapshot, judging the **same** answer against each rubric — one `EvaluationResult` per task (`queue.py:709-714`). `run_detail` took `.first()` of those ordered `created_at desc`, so the panel showed a **single** grade with nothing on screen naming which question it belonged to, and because of the ordering it was the **last** task while the run's own score came from `verdicts[0]`, the first. The panel could therefore disagree with the Results table about the same run. At the reported working shape — 3 stacks × 2 tasks — every run hit this.

Fixed by reusing the newest-per-task rule `results_api.py:48-51` already applies, rather than inventing a second one, so the two surfaces cannot drift. Plain ascending order would have traded this bug for its mirror image: a re-evaluation writes a second row for the same task (real examples exist 1 h 43 m apart) and ascending would have returned the stale one.

`run_detail` now returns an `evaluations` array carrying each verdict with its task title, ordered to match the group; the scalar `evaluation` is kept for existing callers and now means the group's first task.

## 25. The agent's answer was never rendered anywhere 🟠 ✅ FIXED (2026-08-18)

For a comprehension task the written answer **is** the deliverable, and `run_detail` had been shipping it as `result.final_message` all along. No screen read that field. The default tab was `Patch`, so a run that produced a 5,132-character graded answer displayed *"No patch produced. That is a legitimate benchmark result"* — true about the patch, and actively misleading about the run. Reading the answer meant opening SQLite.

The tab is now `Output` and renders whichever the run produced: the diff for a commit task, the answer for a theory task, and the empty state only when there is genuinely neither. Rendered as wrapped monospace rather than parsed markdown — the repo carries no markdown dependency and this did not justify adding one.

Two smaller things fixed alongside, both consequences of [[Known Defects]] #23: the `error` on a model request was in the payload and typed in `api.ts` but never displayed, so a `503` rendered as a bare number; and `_reconcile_usage` counts **attempts**, so a retried call inflates `requests`. The count is now labelled `attempts, incl. retries` rather than quietly redefined, with an `upstream · n failed` chip and a note that a recovered call appears as several rows.

## 26. A request cap outlived its control and killed a healthy run 🔴 ✅ FIXED (2026-08-18)

`useWizard.ts` kept `const [budget, setBudget] = useState(8)` feeding `max_model_requests` after the control that set it was removed. Nothing rendered `setBudget` or `setUncapped` any more, so **every run launched from the UI was hard-capped at 8 model requests with no way to change it**. The commit that removed the control claimed "the UI simply never sets one" — it did, at 8.

Caught by a live run, not by reading code. `smolagents × openai/gpt-oss-120b` made **8 clean calls in 191 s, zero errors**, and was killed one request short of an answer with `budget_exceeded`. It was the healthiest of three stacks that day.

The bias is the part worth remembering: **a request cap only ever bites fast stacks.** A slow model times out long before reaching 8 and never feels it, so the cap was quietly penalising exactly the stacks this product exists to find. Same class of error as [[Known Defects]] #18 — inferring a model's quality from a limit of ours.

Now `max_model_requests: null` unconditionally. `null` rather than omission is load-bearing: the backend applies its own default of 8 whenever the key is **absent** (`queue.py:53`), so removing the field would have changed nothing. Spend stays bounded by the 30-minute timeout and the input-token ceiling — the proxy's own argument, that a request count says almost nothing about cost, applies here too. Pinned by `Wizard.test.tsx::launches with no per-run request cap`, confirmed failing against `max_model_requests: 8`.

The backend default of 8 is left in place for direct API callers under [[ADR-003 Free Tier Constraints]].

## 27. smolagents discards everything when interrupted 🟠 ✅ PARTLY FIXED (2026-09-07)

A `CodeAgent` holds its answer in memory and emits it only through `final_answer()`. The runner's `except` path sets `error_type`, `error_message` and `traceback` but **never `final_message`**, and on timeout the process is SIGKILLed (exit 124) before it writes its output file at all. So any interruption yields a zero-length answer no matter how much the agent explored.

Measured on `smolagents × nemotron-3-ultra-550b-a55b`: 6 requests, 119,678 input and 42,275 output tokens, **0 characters of answer**, both grouped tasks scored 0.0. mini-SWE-agent does not have this failure mode because it files `ANSWER.md` to disk as it goes, so a partial answer survives the kill.

Salvaging the last step's output would be legitimate rather than score inflation — `effort` already exists to distinguish "explored nothing" from "explored plenty and we threw it away" — but it is a change to what gets graded and wants its own decision.

**Fixed for the clean-exit case (2026-09-07).** The runner now falls back to the last step that produced text when `result.output` is empty, trying `model_output`, `action_output`, then `observations`. Flagged rather than silent: `answer_salvaged` rides in `harness_meta`, because a salvaged answer is not the agent's declared answer and the record has to say which one was graded. Three tests execute the real RUNNER source against a stub `smolagents` — declared answer preferred, last step salvaged, and an agent that genuinely produced nothing still scores nothing.

**Still open: the SIGKILL case.** On timeout the process dies before writing its output file at all, so there is nothing to fall back to. Salvaging that needs the runner to checkpoint as it goes, which is a larger change.

## 30. The judge graded plausibility, not correctness 🔴 ✅ FIXED (2026-09-07)

The rubric author read only manifests and the file tree — `build_digest` gates content on `_is_manifest(name) or in_ci`, so **no source is ever read** — and the judge received the tree, the rubric and the answer, also with no source. Between them they could confirm that an answer covered the rubric's topics and named files that exist. Neither could tell a correct trace from a confident wrong one, and correctness carries **50% of the ranking weight**.

Concretely: a criterion asked for *"exactly when paralysis, burn, and poison checks occur relative to attacks and end-of-turn"* — written about `battle_mechanics.py` by a model that never opened it, and graded by a model that never opened it either.

Now `digest.read_evidence(root, paths)` reads the source behind each criterion's cited path and `judge_answer` passes it through. Deliberately in `digest.py`: that module owns the rule about what may leave the machine, and this is a real widening of it — grading needs the module that implements a call order, not a README. Still bounded (6,000 chars per file, 30,000 total) and still secret-safe: resolved inside the repo root so a crafted path cannot escape, and refused for anything matching `SECRET_PATTERNS`. `build_digest` is unchanged, so setup analysis still sees only manifests.

The system prompt now instructs that a claim contradicting the source is `missed` however well it reads, and that a criterion whose file is absent is judged on coverage as before. `evaluation_results` records `evidence_files`, so a coverage-only score is distinguishable from a checked one rather than both reading as a bare number.

**Not claimed:** this does not make the judge infallible. It replaces "sounds plausible" with "consistent with the source it was shown", which is a different and much better measurement — but the judge is still a model, and still not deterministic (Known Defect #17).

## 31. Eligibility judged every task on a patch, so no theory stack could ever win 🔴 ✅ FIXED (2026-09-18)

`aggregate.py:104` read `all(not s.patch_produced for s in samples)` regardless of task kind. A comprehension task answers in prose and produces **no patch by design**, so every theory stack was permanently ineligible and the recommendation fell through to whatever scored worst-but-patched.

Found by a UI QA sweep, not by a test. On experiment `27ce581a` the page recommended `mini-swe-agent × gpt-oss-120b` at **0.33** while excluding a **0.92** smolagents run as *"never produces a patch"* — the product's headline output, wrong, on the one screen it exists to produce.

`RunSample` now carries `task_kind`, populated in `results_api.py` where samples are already built per task. Theory tasks are gated on a **graded answer** (`score is not None and signal == "ok"`); commit replays keep the patch rule untouched. `judge_answer` already returns 0.0 with an explicit error when no answer arrived, so a stack that produced nothing still fails the gate — verified by a test.

Verified against live data after the fix: both mini-swe-agent stacks eligible at 0.417 and 0.542, recommendation correctly `nemotron-3-super-120b`, and the smolagents row still excluded but now for an honest reason — *"more than half of runs time out"*.

**Second half, same defect.** `queue.py` set the run's headline score to `verdicts[0]` — the group's *first* task. The Live card therefore showed **0.833** for a run whose real mean was **0.417**, disagreeing with the Results page about the same run. It now reports the mean across the tasks the run answered; per-task verdicts are still stored individually.

## 32. "SUCCESS 0%" beside a recommendation 🟠 ✅ FIXED (2026-09-18)

`success_rate` counts runs scoring **≥ 0.5** (`aggregate.py:86`). Labelled `success`, the recommended stack read *0% success* while an excluded one read *100%* — two individually correct numbers that together looked like a contradiction, on the page a reader trusts least.

Relabelled to `≥ 0.50` with a title attribute. The maths is unchanged deliberately: it is a meaningful threshold rate, and redefining it would silently change what every saved comparison meant.

## 33. The live tile showed a frozen score that no longer matched Results 🟠 ✅ FIXED (2026-09-18)

Fixing #31 in `queue.py` corrected what gets *written* when a run ends — and nothing else. `_snapshot` reads `run.result["score"]`, a value stamped once at completion, so every run that had already finished kept displaying the old `verdicts[0]`: **0.833** on the tile against **0.417** on Results, for the same run. Caught by the user asking whether the tile had actually been corrected; it had not.

The tile now derives each run's score from its `EvaluationResult` rows — newest-per-task, then the mean across tasks, reusing the rule `results_api` already applies. Verified on the real experiment with no backfill: tile and Results now read 0.4167 / 0.5417 / 0.0 identically, row for row.

The point is the class, not the instance. A stored display value can drift from the data it summarises the moment anything is re-evaluated; a derived one cannot. `run.result["score"]` is still written for the API record, but no surface trusts it as the number to show.

Pinned by three tests, two of them confirmed failing against the frozen field. One covers a run carrying **six verdict rows for two tasks** — a mean over rows rather than tasks would have triple-counted the re-graded one.

**Checked and found already correct:** the plan also proposed stopping `aggregate.py` reporting `0.0` for a stack that produced nothing. `_mean([])` already returns `None`, and the smolagents `0.0` turned out to be a genuine judged score (`signal='ok'`) — the judge ran on a timed-out run that produced no answer and scored it zero. No change made; the distinction the rule protects was already intact.

**Widened 2026-08-18.** Not only on interruption. A `smolagents × gpt-oss-120b` run exited **cleanly** — `exit_code: 0`, `status: completed`, 19 steps, 321,263 input and 21,146 output tokens — with `final_message` empty. Its stdout tail holds a full, substantive answer written as step prose. `result.output` is populated only by `final_answer()`, so an agent that answers without making that call returns nothing at all. Both models tried so far miss the call: the 550B could not emit parseable Python, gpt-oss-120b simply narrated instead. Three smolagents runs, three zero scores, and in at least two the answer demonstrably existed.

## 28. Nothing told a shell agent it could stop 🔴 ✅ FIXED (2026-08-18)

`DELIVER_AS_FILE` said write `ANSWER.md` and *"do not finish without it"* — a negative constraint that was never released. mini-SWE-agent runs `--exit-immediately` and stops the moment the model submits, so the agent was willing to stop and was never told to.

Measured: `mini-swe-agent × nemotron-3-ultra-550b` wrote a complete **1,866-character `ANSWER.md`** — the only file in its patch, answering both grouped questions with `file:line` citations — then explored for roughly 120 more steps and was killed at **6,030,328 input tokens** by the ceiling. 126 requests, of which the useful work was over long before.

The instruction now closes: once `ANSWER.md` exists, submit and end the run. `DELIVER_AS_FINAL_ANSWER` never had this gap, because `final_answer()` *is* smolagents' exit.

This is why the 6M ceiling was **not** lowered in the same change. It was never the operative bound — it was the backstop that caught a run which should have stopped itself, and tuning it would have hidden the actual defect.

## 29. The budget watchdog never graded a comprehension run 🔴 ✅ FIXED (2026-08-18)

`_end_budget_run` called only `_evaluate`, gated on `patch_produced`. A theory task has no `base_commit` and no fixture, so `_evaluate` returned `no_evaluation_configured` and the run recorded no score — while the answer sat in the extracted patch, which `judge.resolve_answer` reads *first* via `answer_from_patch`.

So the run above finished **COMPLETED with no grade at all**, and read as a success only because the agent happened to leave a file behind. Two grouped questions, 28 minutes, 6M tokens, zero verdicts.

Now branches on `task_kind` exactly as the normal path does (`queue.py:698`): `_judge` per grouped task for theory, `_evaluate` for commit. Effort is recorded with `agent_steps` and `commands_executed` **null** — the harness never returned, so those are unknown rather than zero.

Residual, deliberately left: the watchdog still decides COMPLETED vs FAILED from `patch_produced`, so a theory run that answers in its final message and writes no file will carry a real score while reading FAILED.

---

## Severity key

🔴 blocks a correct benchmark result · 🟠 blocks correctness on real repos or lies about status

## Related

- [[Implemented]] · [[Spec Gaps]] · [[Roadmap]] · [[Acceptance Criteria]]
