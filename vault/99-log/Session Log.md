---
tags: [aso/log]
status: current
updated: 2026-08-15
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

## 2026-08-11 — Model list was 402 entries, 12 of them unusable by design

**Why.** The user: *"It is showing many models in the models section."* Three problems behind it, one a real correctness bug.

1. **402 models in a flat checkbox list.** The wizard called `api.models(false)`. Only 14 of 402 are free, and this account has no credits, so the rest were 388 ways to fail. Now free-only by default with an explicit `include paid` opt-in, a name filter, and a count in the header.
2. **Closed-source paid models were selectable** (Claude, Gemini). Spec §2 puts them out of scope. Revealing them now carries a warning that says so, and notes open-weight-but-paid (Kimi, GLM) is fine with credits.
3. **12 moving aliases were pinnable** — `~anthropic/claude-opus-latest` and friends. These follow the vendor's current release, so **a rerun could silently measure a different model**. That is exactly the hazard §4 bans `openrouter/free` for, and it would quietly invalidate any longitudinal comparison.

**Fix location matters.** The alias ban went into `providers/openrouter.py` beside the existing `openrouter/free` ban — same rule, same place — as `is_moving_alias()` plus an `is_alias` flag on `ModelInfo`. `validate_model()` now refuses to pin one, so the listing excludes them by default rather than offering a choice that fails at snapshot time. The API also sorts free and tool-capable first, because with 400 models the ordering *is* the usability.

**Verified.** Default listing returns 14, `free_only=false` returns 390 (402 − 12 aliases), and zero aliases in either. Suite 112 backend (+3) and 22 frontend; lint, typecheck, build green. Recorded in [[Free Models]].

---

## 2026-08-11 — GitHub clone race fixed; AI-assisted setup added

**The bug.** A user's GitHub repo showed no commits. The repo was fine — public, 23 commits, all with parents. `clone_github` destroyed and re-cloned on every call, and backgrounding the baseline (my own change, the previous entry) made that concurrent with the commits query, so one deleted the tree the other was reading. Recorded as [[Known Defects]] #15 — the first defect I caused rather than found. Now clone-once/reuse-after with a per-repo lock; measured 34.8s first clone, **0.4s** on reuse.

**AI-assisted setup.** A "Suggest with AI" button on the review step infers build/test commands and nominates commits worth benchmarking. Deliberate, never automatic: one press costs one of ~50 daily requests, and that budget exists for benchmark runs.

**The security shape matters here.** This is the *only* feature that transmits repository content to a third party — agent sandboxes are sealed and reach nothing but the proxy. So `digest.py` works from an **allowlist** of file types worth sending (README, manifests, CI config), never a blocklist of bad ones, with a second `is_secret()` filter over `.env*`, `*.pem`, `*.key`, `id_rsa*`, `*secret*`. Tests plant a `.env` and an `id_rsa` and assert neither is even *named* in the digest. The button states what it sends before it is pressed.

**The AI never gets the last word.** Suggestions land as editable field values with per-field rationale, are never auto-saved, and mark the baseline stale — so the baseline then proves empirically whether the suggested test command works. Parsing is paranoid: blank commands stay absent rather than being invented, and a hallucinated sha is dropped because it could never be replayed.

**Verified on the user's real repo.** Commits list populates in the UI. The suggestion returned `confidence: low` and its own rationale admitted *"no explicit test suite; however, pytest is a common…"* — correctly flagging a guess. Worth noting for that repo: **no tests means no correctness signal**, so it will produce a failing baseline rather than a benchmark.

**Suite** 133 backend (+21) and 25 frontend (+3); lint, typecheck, build green.

---

## 2026-08-12 — Baseline and evaluation moved into containers

**Why.** A baseline reported INSTALL pass / TEST exit 2 / 0 tests. `pip` wrote to miniforge 3.13 while pytest ran under uv's 3.12 — the venv has `pytest` but no `pip`, so they resolved to different interpreters. Install "succeeded" at installing nothing. [[Known Defects]] #16.

**Fix.** `sandboxes/container_exec.py` — the executor `exec.py` always said was coming ("HostExecutor runs on the host; the Docker executor lands in Stage 4 behind the same shape"). `baseline.py` and `evaluators/engine.py` now take an `execute` callable defaulting to the host one, so unit tests stay fast and Docker-free while production runs in a container.

**Caching was not optional.** Web_Scraper pulls streamlit, langchain, selenium, playwright and faiss-cpu — minutes per install, paid per evaluation *and* per agent run, since the sandbox PREP phase installs too. A 36-run matrix was hours of pure installation. `sandboxes/prepared.py` builds one image per repo keyed by a manifest hash; `SandboxManager.create` takes an image override so the agent's install collapses to a no-op as well.

**Why the cache is safe:** the install command still runs inside the container. Normally a no-op, but it picks up a dependency an agent's patch adds. A failed build is reported as the baseline's install step with its log rather than an opaque build error.

**Hardening kept in one place.** Container creation flags moved to `manager.container_kwargs()`, shared by agent and evaluation containers — configured separately they would drift, and the weaker one is what would matter.

**Bug caught in my own helper:** the evaluator grades in `workdir/graded`, but the executor hardcoded `/workspace`. It now translates the requested directory into the container. Covered by a test.

**Verified.** 10 new Docker-gated tests including the one-interpreter regression and installed-then-importable — the exact reported failure. 143 backend + 25 frontend; lint, typecheck, demo green. `docs/architecture.md` and [[Evaluation Engine]] corrected: both said evaluation runs on the host.

---

## 2026-08-12 — `python -m` command forms; a repo finally baselines

**Why.** `Pokemon-Battle-Simulator` still failed after the container fix, with `ModuleNotFoundError: No module named 'src'`. Its `src/` is a proper package, `tests/` has no `__init__.py`, and there is no pytest config — so bare `pytest` puts `tests/` on `sys.path` and the repo root never gets there.

**Fix.** `detectors.py` now emits `python -m pip install …` and `{prefix}python -m pytest -v`. Same commands, interpreter pinned to whatever `python` is, and CWD on `sys.path`. Repos that already worked are unaffected; src-layout repos start working. `tests/test_src_layout.py` proves the mechanism with `python -P` (which disables CWD-on-path, isolating the one variable) rather than leaving it as a comment.

**A worse bug found while verifying.** With pytest absent the baseline reported **benchmarkable: True with 0 test cases** — it only failed on a parsed `collection_error`, and "No module named pytest" parses as nothing at all. That would let a full matrix run against a repo whose tests never execute, scoring every agent against silence. Now a test command that exits non-zero AND yields zero cases is not benchmarkable.

**Verified end to end on the real repo:**
- detected commands are the module forms, nothing to hand-edit
- baseline **19s first, 2s cached** — the prepared image is working
- without pytest: correctly refuses, and the panel shows `No module named pytest`
- with pytest added: **5 test cases, 3 passed, 2 failed**, benchmarkable with a warning

Both original bugs are gone: `pandas` imports (containers) and `src` imports (`python -m`). The 2 remaining failures are the repo's own — a coroutine never awaited, and async tests with no `pytest-asyncio`. Precisely what the baseline exists to record so an agent is never blamed for them.

**Suite** 148 backend + 25 frontend; lint, typecheck, demo green.

---

## 2026-08-12 — NVIDIA NIM as a second provider

**Why.** OpenRouter's ~50 requests/day has gated every milestone in this project. A second provider buys more than the other three ideas on the table combined. Spec §4 already named "any OpenAI-compatible endpoint"; `ModelProvider` was the seam. [[ADR-005 Second Provider]].

**Verified live**: `GET /v1/models` returns 102 models, 49 code-oriented, and needs no key to list.

**The interesting part was what NIM does not tell us.** Its listing carries only `id`/`object`/`created`/`owned_by` — no pricing, no context length, no `supported_parameters`. `ModelInfo.supports_tools` was a plain `bool`, so a NIM model would have had to claim `False`: asserting a model *cannot* use tools when we simply cannot see. That is a fabricated metric, so the shared contract became `bool | None` and the UI renders **`tools unknown`**, never `no tools`. Same reasoning for cost: NIM bills credits, so `is_free` is False and a NIM run does not display "$0.00" the way a genuine `:free` model does.

`is_moving_alias()` moved from `openrouter.py` to `base.py` — an alias is unpinnable for any provider, and a rule living inside one provider is a rule the next one forgets.

**Found while verifying:** an empty key produced `Bearer `, which httpx rejects client-side with an opaque `LocalProtocolError`. The header is now sent only when a key exists, so keyless listing works (as the API allows) and a real auth failure surfaces as the server's own 401.

**Also caught:** `npm run build` failed where `tsc --noEmit` passed — `api.connection` gained an optional argument and react-query was handing it a `QueryFunctionContext`. Worth remembering that the two typecheck paths are not equivalent.

**Verified.** 9 NIM tests + 2 frontend, all keyless via `MockTransport`: unknowns stay `None`, NIM is never free, 429 maps to `RATE_LIMITED` so existing backoff applies, tools pass through, aliases rejected, and two providers route independently in one experiment. Suite 157 backend + 27 frontend; lint, typecheck, build, demo green.

**Next.** `tools unknown` is the best argument yet for spec §21 **preflight** — settle capability by running the harness once, rather than by trusting listing metadata.

---

## 2026-08-12 — End-to-end flow documented, and why the runs were failing

**Why.** Asked which stage uses what and why, with no single note answering it — [[System Overview]] covers components, [[Run Lifecycle]] covers states, but nothing walked the path from *"here is my repo"* to *"use this stack"*. [[End-to-End Flow]] now does, naming the technology at each of the twelve stages and the reason for it. Versions were read from `pyproject.toml`, `package.json` and the sandbox `Dockerfile` rather than recalled.

**The stack story worth remembering:** one FastAPI process, one SQLite file, and Docker. What is *absent* is the design — no Redis, no Celery, no Postgres, no Kubernetes — because a single-user local tool must start with `make dev` and be debuggable by reading one process.

**Diagnosis in the same pass.** Across 41 real runs: 13 COMPLETED, 22 FAILED. The failures were **not** the models or the agents — every run that got a clean shot succeeded, and `nvidia/openai/gpt-oss-120b` produced both real patches (41/42 requests, 21s median). Failures grouped as: 8× relay severing sockets at 10s, 7× the 120s provider timeout, 3× containers dying mid-run, 2× the loopback bind, 2× an illegal `EVALUATING → TIMED_OUT`, 1× `z-ai/glm-5.2` exceeding NIM's ~300s gateway (0/12 requests — a genuine stack-level incompatibility, not a bug).

**Why it looked systemic** was attribution: `_run_guarded` filed *every* exception as `HARNESS`, so containers Docker killed and networks that vanished were recorded as harness crashes. Harness reliability is the metric that decides the recommendation, so this made it a measure of Docker's mood — mini-swe-agent looked unreliable largely for that reason. Sandbox faults now map to `SETUP`.

**A false message cost real time.** Both adapters raised `"<dep> missing in sandbox image"` on *any* non-zero probe exit, so a dying container reported a missing dependency. The image installs both harnesses and both import cleanly — verified directly in the base and prepared images. Absence is now claimed only when the output says so.

**Self-inflicted, worth recording:** running the test suite beside a live batch destroyed all 8 of its runs. Container-creating tests live in three files, not the one obvious file, and excluding them by filename got it wrong. They carry a `docker` marker now — use `pytest -m "not docker"` while a run is in flight.

**Next.** A repo with a runnable test suite. `Web_Scraper` and `Ai-Web-Scraper` produce patches but can never be scored — every run ends `INSUFFICIENT_EVALUATION_SIGNAL`, which is correct behaviour and also a dead end for ranking.

---

## 2026-08-14 — The analyzer was calling a dead key, and OpenAI speaks a different dialect

**Why this came up.** A benchmark run against `Pokemon-Battle-Simulator` needed `POST /repositories/{id}/evaluation-strategy`, which returned a bare 500. The strategy ladder is the one call that decides whether a repo can be scored honestly at all, so a 500 there is not cosmetic.

**First cause was not in the code.** `select_analyzer` walks `PREFERENCE = (anthropic, openai, openrouter, nvidia)` when `ANALYZER_PROVIDER=auto`. `ANTHROPIC_API_KEY` was **not** in `.env` — it was an exported shell variable inherited by the uvicorn process from an old LiteLLM setup, and pydantic-settings ranks process env **above** the `.env` file. So `auto` picked Anthropic and authenticated with a dead key. Worth remembering: `.env` is not the whole configuration surface, and `ps eww -p <pid>` is the way to see what the server actually got.

Pinned with `ANALYZER_PROVIDER=openai` rather than by hunting the stale export — an explicit provider bypasses `PREFERENCE` entirely, so it is immune to whatever the shell is carrying.

**Second cause was two vendor dialect mismatches**, [[Known Defects]] #17. gpt-5.x rejects both `max_tokens` and an explicit `temperature`; gpt-4.x accepts both. Measured, not assumed — the four-way probe is what made the fix per-model instead of per-vendor guesswork. `max_completion_tokens` turned out to work on *both* families, so that one is an unconditional rename; `temperature` genuinely varies, so it stays a model check.

**Result:** the ladder now returns 200 in 20s via `openai / gpt-5.6-sol` — `repo_tests`, `scoreable: true`, `warn: true`, rung 1 (`commit_tests`) correctly rejected with `commit_test_files: 0`, rung 2 repairing a missing runner to parse 5 test cases.

**And a finding worth more than the fix.** The ladder certifies this repo `scoreable: true`. Three of its five tests have bodies that are literally `pass` — they cannot distinguish a correct patch from a no-op — and the other two fail at baseline. `warn: true` is set, but a caller reading `scoreable` alone would rank a meaningless score. Correctness is 50% of the weighted score. Not filed as a defect yet because the right fix is a judgement call about what `scoreable` is *for*.

**Also found, not fixed:** [[Known Defects]] #18 — preflight's `max_tokens=1` probe makes OpenAI return a 400 for reasoning models, which `probe` reads as permanently unusable. Repository analysis is unaffected (it asks for 1200), but an OpenAI benchmark combination would be silently deleted. One-line fix, but it changes probe cost for every provider, so it needs an explicit call under [[ADR-003 Free Tier Constraints]].

**Verified.** 238 backend tests (`-m "not docker"`, the live server holds `data/aso.db`), lint and typecheck green. `tests/test_openai_provider.py` pins both wire spellings and that gpt-4.x keeps `temperature=0.0`. One flake seen and cleared: `test_relay.py::test_relay_waits_for_a_slow_response` failed once under full-suite load, passed 3/3 alone, and mentions nothing this change touched.

**Caveat on "OpenAI only".** `POST /repositories/{id}/suggest-setup` is still hardcoded to `OpenRouterProvider` and 409s without `OPENROUTER_API_KEY` — the same bug `analyzer.py`'s docstring claims fixed, which was only fixed on `/evaluation-strategy`. Do not remove the OpenRouter key.

---

## 2026-08-14 — The repo gets a test that can actually fail

**What changed.** Setup is now model-driven end to end, and the thing that grades an agent is proven rather than assumed.

- **`/suggest` honours `ANALYZER_PROVIDER`.** It built an `OpenRouterProvider` directly and 409'd without that key, so two adjacent buttons in the wizard spent two different vendors' quota and only `/evaluation-strategy` obeyed the setting. Now both route through `select_analyzer`. Net −10 lines, plus `suggest_model` deleted as orphaned config.
- **Generated hidden tests** (`tasks/generate_tests.py`, new). When a commit ships no tests of its own, a model writes one — and it is only offered if it **FAILS at the parent commit and PASSES at the solution commit**, checked per pytest case rather than by exit code. Up to 3 attempts, each rejection fed back as a nudge. A candidate that does not appear at all at the parent is rejected, not assumed to have failed: the usual cause is a module-level import of something that only exists after the fix, which breaks collection for the whole suite.
- **Model-written task prompts** (`historical.ai_task_description`). The model reads the diff; the agent never does. The framing wrapper is unchanged and shared, and an **enforced** leak guard rejects diff syntax or three consecutive lines of the fix, falling back to the deterministic description.
- **Test-environment repair** (`repositories/repair.py` + `POST /repositories/{id}/prepare-tests`). Only dependency manifests, test config and test files may change — enforced on the returned diff, because repairing `src/` would delete the bug the agent is asked to fix and hand every harness full marks. Kept only if it measurably improves the baseline, ranked usability-before-passing so a patch that breaks collection cannot look like an improvement.
- **The fixup applies inside `materialize_workspace`**, which builds *both* the agent's workspace and the graded tree. Applying it at either call site instead would give the agent a different repository from the one that scores it, and nothing would fail — the numbers would just stop meaning anything.
- **Unfailable tests no longer vote** (`detectors.vacuous_test_names` + `engine.py`). An AST pass names `test_*` functions whose body is only `pass`, a docstring or `...`; those cases are dropped from the correctness denominator but still watched for regressions.

**Why.** `Pokemon-Battle-Simulator` has five tests: three whose bodies are `pass`, two already failing and therefore excluded as pre-existing. Nothing in it could distinguish a correct patch from an empty one, which is how `Update README.md` once scored 0.6.

**Verified, live, against the running backend.** `/suggest` answered from `openai/gpt-5.6-sol` and narrowed 11 commits to **1** — `3e4e48de "corrected the server.py file"` — with a reason. Preparing that commit produced `tests/test_aso_generated_3e4e48d.py::test_mega_kick_is_available_in_the_offline_move_cache`, **failed at parent `939e8b61`, passed at `3e4e48de`**. First test in this repository capable of separating a correct patch from a no-op. Prompt came back present-tense and code-free, past the leak guard.

**One bug found and fixed mid-verification.** The first live attempt returned an empty test file and gave up after one try: `GenerationError` conflated "model declined" with "model produced junk". Split into `NoBehaviouralChange` (do not retry — the diff will not change) versus everything else (retry). The emptiness itself was reasoning-token starvation at `max_tokens=1600` — see [[Known Defects]] #18, which this confirms is general rather than specific to the one-token probe.

**Verify:** `make lint`, `make typecheck`, `pytest -m "not docker"` → **291 passed** (was 238; +53 new), `make demo` → 2 runs COMPLETED. Frontend `tsc --noEmit` clean and `npm run build` green.

**Still true and still biting:** the repo commits `src/__pycache__/*.pyc` and `.log` files, which show up in the prompt's orientation list and previously broke `git apply`. Repo hygiene, not ours to fix.

---

## 2026-08-15 — A live 2×1 run found two ways the harness lies about a result

**The run.** Experiment `e6240a5e`: `smolagents` vs `mini-swe-agent`, both on `nvidia/openai/gpt-oss-120b`, one task — commit `3e4e48de`. **Both FAILED, budget_exceeded, neither produced a patch.** Near-identical profiles: 8/8 requests succeeded, 0 failed, `rate_limited` false, 40,610 / 32,444 tokens in.

It was launched through the pre-generation path: the prompt was the raw commit subject — *"corrected the server.py file"*, five words, past tense — and **no hidden tests were attached**. That is the prompt shape this log already records as producing "Acknowledged… please provide a specific task" and no edits. Two harnesses spent 16 successful model calls agreeing there was nothing to do.

**Defect A — the failure message diagnosed a cause nobody measured.** `queue.py` wrote a constant on every budget exhaustion: *"the harness kept retrying a terminal 429 instead of stopping"*. True of the incident that prompted it, false here — 8 of 8 succeeded and nothing was throttled — and it cost real time chasing a rate-limit problem that did not exist. Now `budget_failure_message(usage)` composes from the counters already in scope: the retry-storm wording only when `failed_requests > 0` or `rate_limited`, otherwise what actually happened. Asserting an unmeasured cause is the same class of error as a fabricated metric, and it had been sitting in the one string a user reads when a run dies.

**Defect B — pre-existing failures still sat in the score denominator, and I put them there.** Yesterday's change dropped unfailable tests from scoring. On this repo's baseline — three `pass` bodies plus two tests already broken — that moved the score from a falsely high **3/5 = 0.6** to a falsely low **0/2 = 0.0**. Inverting a bug is not fixing it. `engine.py` now excludes both kinds, using the `baseline_cases` that `_regressions` already consumes, and reports `excluded_unfailable` / `excluded_pre_existing` / `scoreable_cases` so the exclusion is visible.

**And `has_signal` was answering the wrong question.** It was `report.parse_ok or bool(report.cases)` — output we could *read*, not output that *means* something. A suite of only unfailable and already-broken cases parses perfectly and distinguishes nothing. Now `bool(scoreable) or bool(regressions)`. This is what makes the fix land: `INSUFFICIENT_EVALUATION_SIGNAL` → `aggregate.py` marks the combination ineligible → no winner is drawn from noise, per the invariant in `CLAUDE.md`.

**Verify:** `make lint` ✅ · `make typecheck` ✅ · `pytest -m "not docker"` → **297 passed** (+6) · `make demo` ✅. New: `tests/test_budget_message.py`, plus a case in `test_vacuous_tests.py` built from this repo's exact five-case baseline asserting the answer is *no signal* — not 0.6 and not 0.0.

**To make a rerun mean anything:** press **Prepare & verify tests** before launching (that commit yields a test proven to fail at `939e8b61` and pass at `3e4e48de`), approve it, and raise the request budget above 8 — NVIDIA is credit-billed, so ADR-003's daily cap does not bind.

---

## 2026-08-15 — Let the agent stop when it is done, and measure the thing that kills it

**Asked for:** remove the request limit and let agents self-terminate. Doing that naively would have produced *no benchmark at all*, for a reason nothing in the code made obvious.

**The trap.** `aggregate.py` vetoes a combination on `timeout_rate > 0.5` **and** on `completed == 0`. `TIMED_OUT` is not `COMPLETED`. So the moment runs stop hitting a request ceiling and start hitting the clock, every combination becomes ineligible — however good its patch. Under a cap the same work ends COMPLETED, because `_end_budget_run` salvages it. The timeout path never got the equivalent, so **a timeout holding a gradeable patch now ends COMPLETED**, and the slowness is priced in `execution_efficiency` (15% of the weighted score) rather than used as an eligibility veto. A timeout with no patch is still a failure.

Two things already worked and are worth recording so nobody re-derives them: `mini_swe_agent.py:112` extracts the patch unconditionally, timeout or not, and `queue.py:617` grades before the state branch. The 1800s timeout was always a safe backstop.

**Requests were never the meter.** One measured run spent **3.0M input tokens across 100 requests** — every call resends the whole conversation, so 100 requests cost anywhere from 100k to 3M. `max_requests` is now nullable (uncapped), and `max_input_tokens` — which the proxy has always enforced at `proxy.py:186` and nobody ever set — is the guard, defaulting to 6M. Uncapped stays opt-in and is disabled for free-tier providers, because ADR-003's ~50 requests/day would go in one run.

**Stated plainly: the premise is not yet true.** mini-swe-agent ran to the ceiling at 8 **and** at 100, with `--exit-immediately` set, context growing linearly the whole way. It has never once decided it was finished. Uncapped currently buys "runs until the clock", not "stops when done". The non-termination needs its own investigation.

**The smolagents 137.** `capacity.py` already documented the signature — `exit 137, oom_killed=False` is a VM-level memory kill. Two gaps made it undiagnosable: `SandboxManager.stats()` collects `peak_memory` and **was never called**, and the "raise memory" hint fired only when `oom_killed` was True, precisely the flag this kill leaves false. Both fixed; `peak_memory` is now recorded on every run, and `sandbox_memory_mb` is 2048 → **4096**.

**Trade made on the record:** 4 GiB sandboxes cost the second parallel slot on this 7.65 GiB VM (`max_parallel_runs` 2 → 1). That is headroom the project had already declined — `queue_concurrency` is 1 and `9974714` reverted parallelism for making results worse, not faster. Raising Docker Desktop's allocation buys it back. `test_capacity.py` now pins explicit sizes rather than the tunable default, so arithmetic tests stop failing on legitimate config changes.

**Also fixed:** a retried run kept the previous attempt's `completed_at`, so a row read `started_at 12:40:45` against `completed_at 12:35:44` and every derived duration was negative. Cleared on both paths back to PENDING.

**Verify:** `make lint` ✅ · `make typecheck` ✅ · `pytest` (**full suite, docker-marked included**) → **323 passed** · `make demo` ✅ · frontend `tsc` clean, `npm run build` green. First run of the docker-gated sandbox tests this session.

---

## 2026-08-15 — Supervised benchmarking: the analyzer proposes, the harnesses answer, the analyzer grades

**Why.** Every route to an execution-based correctness signal on a real repo has failed, and each failure was in the repository rather than in the agents: three tests whose body is `pass`, no tests in any commit, generated tests that verify one hour and fail the next, and a graded container with no pytest in it. A question like *"trace the execution flow of the move lookup"* needs none of that infrastructure and still measures what a coding harness is for.

**The pytest gap — the root cause of this morning's 0.0.** `requirements.txt` never mentions pytest. `baseline.py` noticed and installed it; the evaluator did not. So grading ran `pytest -v` in a container without pytest, died in 55 ms, collected nothing, and the three tests that passed at baseline looked like they had *vanished* — recorded as three regressions, which supplied a 0.0 that looked measured. Two harnesses were then ranked on a 0.0 vs 0.0 tie. Runner repair now lives in `evaluators/runner_repair.py` and both paths call it; a suite that collects nothing reports `suite_failed` and INSUFFICIENT_EVALUATION_SIGNAL instead of inventing regressions; and the evaluator finally keeps the failing output, which is why diagnosing this needed a manual `docker run`.

**Comprehension tasks** (`tasks/propose.py`). The analyzer reads the digest and proposes architecture / execution-flow / feature-plan questions — **and writes the rubric in the same call, from the same digest**. That is what makes the grading grounded rather than vibes, and it means both harnesses are scored against an identical list. Every criterion cites a path, and **any criterion whose path is not in the real file tree is dropped before the rubric is stored** — a hallucinated rubric would otherwise mark every answer wrong with total confidence. Dropped criteria are surfaced, not hidden.

**The judge** (`evaluators/judge.py`) is grounded and blind. It gets the answer, the rubric and the real file tree; it never gets the harness or model name, because ranking harnesses is the entire point. `invented` — names the answer claims exist and the tree does not contain — is a lookup, not an opinion. **The score is counted here from rubric hits, never taken from the model**: asked for an overall number, a model rounds its own impression up, and a criterion it invents cannot be credited because matches are checked against the rubric we sent.

**Answers** arrive via `ANSWER.md` in the workspace, falling back to `final_message` — smolagents truncates that at 4000 chars, so the file has to come first. Theory tasks snapshot HEAD (there is no "before" state and nothing to leak).

**ADR-005** records the reversal of *"do not use historical-patch similarity as a correctness metric"*, with its cost stated: a correct fix written differently from the original scores low. Judged diff averages with the test score rather than replacing it, and both halves are reported separately.

**`POST /experiments/{id}/summary`** writes the plain-language comparison. Deliberately on demand — it costs a model call and would read differently on every page load.

**The caveat that matters.** The judge cannot be pinned to temperature 0 (Known Defect #17), so scores are noisy. Results now carry that caveat automatically whenever any score came from a judge, and say to compare distributions across repetitions rather than two single numbers.

**Verify:** `make lint` ✅ · `make typecheck` ✅ · `pytest` **342 passed** (full suite, docker included; was 323) · `make demo` ✅ · frontend build green.

**Caught while verifying:** `npx tsc --noEmit` passed on a missing `Button` import that `npm run build` rejected. `make typecheck` does not catch every build failure — the same blind spot as the earlier MUI/vite break. Run the build before believing typecheck on frontend changes.

---

## 2026-08-17 — Per-repo environments, and comprehension without a baseline

`Eval-Personalised-Harness` failed its baseline with `make: not found`. The missing `make` was real but it was **the least of three stacked defects**, and fixing it alone would not have helped. The build log gave the rest away: `transferring context: 138B` — the generated Dockerfile and nothing else.

1. `make` and `uv` were absent from the sandbox image.
2. `Makefile` was not a recognised manifest, so it was never copied in.
3. Manifests were discovered **root-only** and copied **flattened to their basename**. A repo keeping `backend/pyproject.toml` contributed nothing, and `cd backend && uv sync` could never have found its file. `detectors.py` has the same root-only blind spot.

**`sandboxes/environment.py`** now resolves an `EnvironmentSpec` — system packages from a fixed allowlist, plus the files to copy — searching one directory deep and preserving paths. A repo Dockerfile is read for its `apt-get install` lines as *evidence*; it is never built, because its `FROM` would discard the harnesses. The allowlist is enforced on the result rather than requested in a prompt, following `repositories/repair.py`: system packages decide what the benchmark can compile, so the set has to be auditable.

**The find that mattered more than the original bug.** Containers bind-mount the host workspace over `/workspace`, so an image that populated `.venv` or `node_modules` in there has its work erased the instant the container starts. `pip install` reaches site-packages and survives; `uv sync` and `npm install` do not. The prepared-image cache was therefore spending minutes producing layers the mount discarded — a full `make setup` build measured **over ten minutes** before being thrown away. Those installs now skip the image entirely and run in-container, where the test step can see them.

**A failed install no longer ends the baseline.** It names the missing tool (`missing_tool`, exit 127 / "not found"), records a warning, and lets the test step decide. Reporting `make: not found` — a gap in *our* image — as "this repository cannot be scored" threw away stdlib-only repos that pass their suite with no install at all. A dead suite still yields no signal, so this degrades without papering over.

**Comprehension tasks never trigger a baseline.** `queue._prepared_image` returns `None` for `kind == "theory"`: the agent reads code, it never installs or runs a suite. On the frontend the baseline used to fire on *registration*, before the task type was known; it now waits until a commit or user-defined task is picked. `describedTaskIds` was split into `theoryTaskIds` and `describedTaskIds` — the single list held both, which made "are all selections theory?" unanswerable.

**Image:** `make`, `build-essential` and `uv` join the base, with a `make sandbox-image` target because none existed. Verified in the rebuilt image: GNU Make 4.4.1, uv 0.5.11, gcc 14.2.0, Node 20.20.2.

**Verify:** ruff ✅ · mypy ✅ · **379 backend passed** (was 375) · frontend **41 passed**, build + tsc + oxlint green. End to end: the per-repo image for the failing repo now builds with `Makefile` at `/workspace/Makefile`, `backend/uv.lock` at its real path, and `make setup` genuinely running — `.venv` and `node_modules` both present.

**One existing test changed intent deliberately**: `test_prebuilt_install_failure_blocks_and_keeps_its_log` became `..._warns_and_keeps_its_log`. Keeping the log and attributing it to install still holds; halting does not.

---

## 2026-08-17 — A stack is a pair you choose, not a cell in a grid

Agent Stacks ticked harnesses in one list and models in another and silently multiplied them, so two harnesses and three models was always all six pairings. A single global `provider` meant every model had to come from the same one, which made an NVIDIA-hosted model and an OpenRouter-hosted one impossible to compare in one matrix.

**The backend never had this restriction.** `POST /experiments` has always taken `combinations: list[{harness, provider, model_id}]` and iterated it verbatim (`routes.py:218`). Only the frontend insisted on a product. `POST /experiments/preview` was the one server-side holdout, computing `len(harnesses) * len(model_ids)` — it would have reported 4 for a matrix the server was about to queue as 2.

**`Stack` is now a value** (`useWizard.ts`), and the provider belongs to it rather than to the experiment. The picker keeps crossing what you tick *in one visit* — a sweep should not cost more clicks — but visits **accumulate**, deduplicated on the whole triple. One model on two providers stays two stacks; the same triple twice stays one. Each card carries a `remove`, and because `StackCard`'s body is itself a `<button>`, that control sits in the `status` slot rather than nested inside it.

**A consequence worth naming:** `uncapped` was gated on the single provider's `has_free_tier`. With a mixed matrix that becomes "any selected stack is on a free tier" — otherwise one OpenRouter stack added to an NVIDIA run would quietly offer an uncapped run that spends the daily quota.

**Verify:** ruff ✅ · mypy ✅ · **381 backend passed** (was 379) · frontend **46 passed** (was 41), build/tsc/oxlint green. Walked in a browser against a backend built from this branch: `mini-swe-agent × north-mini-code` on openrouter plus `smolagents × deepseek-coder` on nvidia → **two cards, two providers, Review reads `stacks 2` and `total runs 2`**, and removing one leaves one rather than re-multiplying. Preview confirmed directly: two hand-picked pairs → `2 stacks × 1 tasks × 1 reps = 2 runs`; the old product form still returns 54.

**Not tested, and why:** a creation-path test for "2 of 4 pairs" needs two distinct models or two non-sandboxed harnesses, and the fake provider ships one of each — anything else spawns Docker mid-test. The arithmetic is covered at preview instead, and the creation loop is pre-existing and already exercised.

---

<!-- New entries above this line -->
