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

## 2026-08-11 — Phase 4: smolagents harness (two harnesses live)

**What.** `app/harnesses/smolagents_agent.py`, registered in `main.py` and added to `SANDBOXED_HARNESSES`. `smolagents==1.26.0` pinned into the sandbox image alongside `mini-swe-agent==1.14.0`. The matrix can now actually compare two harnesses — see [[Product Goal]] on why that is the whole point.

**API verified, not guessed** (spec §3). Introspected smolagents 1.26.0 directly: `OpenAIServerModel(model_id, api_base, api_key)` targets the run-scoped proxy; `CodeAgent(tools, model, max_steps, additional_authorized_imports)`; `run(task, return_full_result=True) → RunResult(output, steps, token_usage, ...)`.

**The finding that mattered.** smolagents' local Python executor does **not** expose the `open` builtin, so a CodeAgent cannot write files with it. Probing showed `pathlib` works once authorized — so `additional_authorized_imports` includes `pathlib` (plus os/sys/re/json/shutil/subprocess). Without this every run would produce an empty patch that *looks* like a model failure but is really a config bug.

**Design.** The runner script and task text are base64'd into the container's `/tmp` (tmpfs), never `/workspace` — anything written there would be swept up by `git add -A && git diff --cached` and graded as the agent's own patch. Unlike mini-SWE-agent, smolagents reports real token usage, so it is recorded rather than left null.

**Verified.** 6 adapter tests against a stubbed sandbox: real usage reported, runner/task confined to /tmp, run token passed as env and never written to disk (and no real key anywhere), agent failure categorized rather than swallowed, unparseable report doesn't crash or fabricate, missing dependency fails loudly. Image confirmed to carry smolagents 1.26.0 + mini-swe-agent + git. Suite 96 backend + 7 frontend; lint, typecheck, demo green.

**Next.** [[Milestones]] Milestone A. Plan: validate one real cell (~8 requests) before spending the rest of the daily quota on all six.

---

## 2026-08-11 — First real model runs: five more defects, all fixed

**What happened.** Attempting [[Milestones]] Milestone A surfaced five defects the entire test suite could not see, because nothing had ever executed a real run. Each alone made a sandboxed benchmark impossible. All are now fixed and recorded as [[Known Defects]] #10–#14.

**The big one (#10).** Sealing killed the proxy path. An `internal: true` network has no default route *at all* — including to the host gateway — so `host.docker.internal` died with egress. Both `docs/architecture.md` and [[Sandbox]] claimed otherwise; both are now corrected. Because `seal()` only checked that egress was dead, sealed runs made **zero model requests and reported COMPLETED**. Fixed with a per-run relay container straddling both networks, and `seal()` now fails closed in *both* directions.

**The lesson.** Every one of these hid behind a green suite. A run that exits 0 having done nothing is indistinguishable from a good one unless something asserts it did work — so harness telemetry (stdout tail, tracebacks) is now persisted into `run.result`, and the proxy-reachability assertion is part of sealing.

**What now works, measured.** Up to 20 model requests per run · 27,166 input / 4,222 output tokens · 14 agent steps executing 14 real shell commands · egress refused while the relay stays reachable · budget ceiling fires correctly · both harnesses reach live models.

**What does not work yet.** No combination has produced a passing patch. Two reasons, both legitimate findings rather than bugs: mini-SWE-agent spends its budget exploring (still running tests at 20 requests), and `cohere/north-mini-code:free` emits tool-call JSON where smolagents expects `<code>` blocks. The second is precisely the harness × model incompatibility the product exists to measure, and precisely what §21 preflight ([[Roadmap]] Phase 5) should catch before an experiment runs.

**Quota reality.** `openai/gpt-oss-20b:free` returned **4 consecutive 429s before one success**. Combined with ~50 requests/day and agents needing 20+, [[ADR-003 Free Tier Constraints]] is if anything understated.

**Next.** Phase 5 (preflight) is now the highest-value phase — it would have flagged the smolagents/north-mini-code mismatch without spending a single run. Then raise per-run budgets and retry Milestone A.

---

## 2026-08-11 — Phases 8 & 9: the UI is drivable

**What.** The whole flow is now usable from the browser: register a repo → analyze → edit commands → baseline → add tasks (described or commit replay, with hidden-test approval) → pick harnesses × models → watch live → read the comparison → drill into a run.

**Backend (Phase 8).** New `app/api/live.py`: SSE `GET /experiments/{id}/events` plus `/progress`, `/runs/{id}/detail`, `/runs/{id}/patch`. Events are replayed from the persisted `RunEvent` table rather than an in-memory bus, so a browser that connects late or refreshes still sees the whole run. Also `GET /harnesses` (the UI must not hardcode them), `POST /experiments/preview` (expanded run count), and `POST /experiments/{id}/cancel`.

**Frontend (Phase 9).** Design direction: *laboratory instrument* — near-black canvas, hairline rules, every number in mono, colour strictly semantic (cyan = live, green = pass, red = fail, amber = throttled). Instrument Serif / Archivo / IBM Plex Mono, deliberately not Inter or Roboto. MUI is kept (spec §5 mandates it) but themed hard. Five screens: overview, new-run wizard, live experiment, comparison, run detail.

**Three real bugs the UI exposed** — none visible from the test suite:
1. **Token efficiency was not comparable across harnesses.** Scoring read harness self-reported usage, which smolagents populates and mini-SWE-agent correctly leaves null. Now reads the proxy's usage, recorded identically for every harness. In a product built to compare harnesses this was the worst possible place for an asymmetry.
2. **Experiments never left "running".** Status was set at creation and never updated, so the dashboard showed finished work as in-flight forever. `_settle_experiment()` now marks completion when every run is terminal.
3. **The proxy sent everything upstream.** With a key configured, a `fake` combination was routed to OpenRouter and rejected — the zero-cost path broke the moment a key existed. The proxy now routes per-run by the combination's own provider.

**Disclosed rather than hidden.** `resource_efficiency` is still a copy of `execution_efficiency` (container CPU/memory is collected but never persisted), so its 5% weight adds no independent signal. Rather than let a wrong number render quietly, the results payload now carries that as a caveat and the UI prints it under "read this before trusting the numbers". Real fix needs `SandboxMetric` persistence — [[Roadmap]] Phase 7.

**Verified in a browser**, not just compiled: dashboard, wizard, live view (3/3 progress, real proxy token counts, SSE activity feed replaying `preparing → running → evaluating → completed`), and comparison (4 cards, both Pareto charts, stats table, caveats). No console errors. Suite 109 backend + 17 frontend; lint, typecheck, demo green.

**Next.** Phase 5 preflight is still the highest-value remaining work — it would flag a harness × model mismatch before spending quota. Then Phase 7 to make resource efficiency real.

---

## 2026-08-11 — Wizard asks only for what it needs

**Why.** The user hit the Commands step and said *"I don't even know what to put in build and typecheck."* That was the correct reaction: reading the backend confirms **only `test` is load-bearing**. `engine.py` runs build only `if build_cmd := commands.get("build")`; `baseline.py` does `if not cmd: continue` for install/build/lint/typecheck. Blank is the *right* answer for most Python repos, and the UI implied it was an omission. A UI defect, not user error.

**Five steps → three.** Repository → Task → Configure & review.
- Repository now fires the **baseline in the background** on submit, so it stops being a step. It reads the `RepositoryCommand` row analyze already wrote, so nothing had to move.
- Task offers **both** modes (the user asked for the choice): a pre-loaded tick-list of recent commits — zero typing, and the strongest signal since real tests shipped with the commit — plus free-text for work not yet in history. Ticking caches sha → task id so re-ticking costs nothing.
- Configure & review leads with harness/model pickers and the matrix. Detected setup and baseline live in a **collapsed** panel summarised as `python · pytest · baseline passed`, which **opens itself only** when there is no test command or the baseline is not benchmarkable.

**Labelling.** `install`/`build`/`lint`/`typecheck` now read `(optional)` with "leave blank to skip". `test` is the only field that can block, and says why: *"no test command — there is no correctness signal without one."*

**Two UI defects found while testing this.** MUI `Collapse` keeps children mounted, so collapsed form fields stayed tab-focusable while invisible — fixed with `unmountOnExit`. And the Start button showed only the *first* blocker, which makes it feel permanently dead; it now lists every reason.

**Staleness is disclosed.** The auto-baseline runs against *detected* commands. Editing a command marks the result stale and offers a re-run rather than showing an outdated pass.

**Nothing was removed.** Spec §6 still holds — commands remain fully editable, just not in the user's face. Spec §7's warn-and-proceed on a partially failing baseline is preserved; only `benchmarkable: false` blocks, because it genuinely cannot produce a signal.

**Backend.** One addition: `GET /repositories/{id}/baseline` returns the latest result so the review panel can read state without re-running install and the suite. The POST now returns the same shape.

**Verified in a browser** against a real git repo: paste path → land on Task with no commands form → tick a commit → combos step with Setup collapsed and green. Suite 109 backend + 22 frontend; lint, typecheck, build green.

---

<!-- New entries above this line -->
