# Agent Stack Optimizer — Core Loop Implementation Plan

## Context

`generationDoc.md` specifies a local, single-user platform that benchmarks combinations of coding-agent harness × open-weight model (via OpenRouter) × task, against a real Git repository, and recommends the best stack. The full spec is ~9 phases. Per user decision, this pass builds the **core loop**: foundation, repository analysis, provider layer, sandbox + queue, fake harness/provider adapters, results/recommendation UI, and **one real harness: mini-SWE-agent**. OpenHands and smolagents come in a later pass (adapter interface kept ready; **no registry stubs in pass 1** — they appear when integrated, per eng review).

Design doc (approved, 9/10 adversarial review): `~/.gstack/projects/evalHarness/swastik.methi-no-branch-design-20260729-225458.md`. Target user: developers who can't afford Claude Code/Codex-class subscriptions, picking the best free/open-weight stack. Flagged premises to validate early: local-platform adoption (#1) and free-tier rate-limit viability (#4).

User has a real OpenRouter API key via `.env`. Environment verified: Docker 29, Python 3.14 system (pin **3.12 via `uv`**), Node 25, Git 2.52. Greenfield directory.

## Architecture (spec + eng-review decisions)

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic 2, SQLite (**WAL mode + busy_timeout; single-writer queue session; RunEvent batching** — 7A), asyncio job queue in-process, SSE for live updates, Docker SDK (**all Docker/subprocess calls isolated in threads off the event loop**). Structured JSON logging.
- **Dev topology (Tension 3)**: backend runs **natively on the host** (`uv run fastapi dev`) so sandbox containers are plain siblings and paths need no translation; frontend via Vite dev server. Compose packaging deferred (see TODOS.md).
- **Frontend**: React + TypeScript + Vite, Material UI, TanStack Query, React Router, Recharts.
- **Sandbox network (1A + Tension 1, two-phase lifecycle)**:
  - **PREP phase**: container on a normal bridge network — dependency install + baseline run (agent not present, nothing to leak).
  - **AGENT phase**: container attached ONLY to a per-experiment `internal: true` Docker network shared with the backend's proxy listener; no default route, no egress. Proxy is the sole reachable endpoint.
- **Harness placement (3A)**: the harness runs **inside** the sandbox container; sandbox images bundle harness + its pinned deps (one image per harness family). Proxy URL + per-run token injected as env vars.
- **Evaluation integrity (Tension 2)**: post-agent evaluation happens by extracting the patch (`git diff`) and applying it to a **fresh snapshot in a new evaluator-owned container** with evaluator-owned commands. The agent workspace is evidence, never the grading bench. ProhibitedFilesEvaluator rejects patches touching test files/CI config.
- **Shared core (4A, 5A)**: `sandboxes/exec` (one CommandResult schema) + `evaluators/parsers` (pytest/vitest/generic, test-case identity aware) used by BOTH baseline validation and evaluators; single `core/errors.py` **ErrorCategory enum** mapped into by provider, harness, queue states, and telemetry `error_category`.
- **Container hardening**: non-root with explicit UID/GID mapping for workspace ownership (incl. git `safe.directory`), `no-new-privileges`, cap-drop ALL, read-only root FS where feasible, tmpfs limits, CPU/mem/pids caps per spec §12.

### Run lifecycle (state machine + data flow)

```
                       ┌──────────────────────────────────────────────────────────┐
                       │ EXPERIMENT: tasks × harnesses × models × reps            │
                       └──────────────────────────────────────────────────────────┘
 PENDING ─▶ PREPARING ─────────▶ RUNNING ─────────▶ EVALUATING ─▶ COMPLETED
    │        │ snapshot@base       │ harness in        │ patch → fresh
    │        │ PREP net: deps      │ sealed container   │ evaluator container
    │        │ + baseline          │ ↕ proxy only       │ tests/hidden/lint
    │        ▼                     ▼                    ▼
    └──▶ CANCELLED        TIMED_OUT / RATE_LIMITED / FAILED(category from ErrorCategory)
                                   ▲
         restart reconciliation ───┘  (orphan sweep: containers labeled run_id
                                       + stale RUNNING rows → FAILED(crash), retryable)

 Sandbox harness ──OpenAI-compatible req + short-lived run token──▶ backend proxy
                                                (validates run_id, pinned model,
                                                 budgets, spend ceiling; real key)──▶ OpenRouter
```

## Implementation stages (app runnable after every stage; walking skeleton first)

### Stage 1 — Foundation + walking skeleton (Tension 4)
- Monorepo scaffold per spec §26 minus compose-first dev. `uv` backend (Python 3.12), Vite frontend, Ruff/mypy/pytest/pytest-asyncio/ESLint/Prettier/Vitest configured. Makefile targets per spec §28 (`make dev` = native backend + vite).
- FastAPI app: `/api/v1/health`, `/api/v1/ready`, pydantic-settings config, `.env.example` with the four OPENROUTER_* vars.
- SQLite engine setup: **WAL, busy_timeout**, session patterns (7A). **Migrations grow per stage** — Stage 1 creates only the tables the skeleton needs (Repository, BenchmarkTask, Experiment, ExperimentCombination, BenchmarkRun, RunEvent, Artifact); remaining spec §18 entities land with the stage that implements them (Tension 4).
- Structured JSON logging (request_id, experiment_id, run_id, task_id, harness, model_id, event_type, duration, error_category) with `core/errors.py` ErrorCategory enum (5A).
- **Walking skeleton exit criterion**: a FakeHarness run flows queue → sandbox container → fake evaluation → stored result on a tiny fixture, visible via API. Every later stage upgrades a working loop.
- Frontend shell: router, MUI theme, dashboard placeholder, typed client from OpenAPI (regenerated per stage as the API grows).

### Stage 2 — Repository analysis + baseline
- Repo registration: local path (allowlist + `../` traversal guards, size limit) and public GitHub clone. **Clone hardening**: https-only, no submodule recursion by default, hook stripping, object-size/disk caps.
- Pluggable language detectors — strong Python + JS/TS (package managers, dep files, build/test/lint/typecheck commands, test locations, CI workflows, runtime versions); others "detected but unsupported". User-editable commands (API + wizard step).
- **Snapshotting**: `git archive` at base commit → fresh workspace → new git init + synthetic baseline commit. **Explicitly reject** repos needing submodules or Git LFS with a clear error (support later).
- Baseline validation runner (spec §7) using the **shared exec/parser layer (4A)**: PREP-phase container → install, build, test, lint/typecheck → store totals **with per-test-case identity**, output, durations. Warn-and-proceed on partial failure.
- Historical commit listing (base = parent; task text from commit message, editable). PR replay stub.

### Stage 3 — Provider layer + model proxy
- `ModelProvider` ABC; **OpenRouterProvider**: model listing, `:free` variant identification via pricing metadata, exact-model pinning + per-experiment metadata snapshot, validation, connection test, rate-limit state. Never `openrouter/free`; never silently substitute. **Record OpenRouter's returned provider/model routing metadata on every request** (reproducibility).
- Error normalization (402/429/5xx/timeout/invalid-response/context-limit) mapping into ErrorCategory (5A).
- **Inference proxy**: OpenAI-compatible endpoint pinned to what mini-SWE-agent actually calls (verify exact path, streaming, tool-call, and usage-field expectations against its docs before building). Per-run token with **defined renewal semantics for long/rate-limited runs** and expiry on completion; pinned-model enforcement; request/token budgets; **hard per-run AND per-experiment currency spend ceilings enforced before any real-key run**; usage+latency recording with **estimation fallback when providers omit usage** (never inferred from string length; estimates flagged as estimates); secret redaction.
- **FakeProvider** for tests/demo. Live verification against the real key (model listing + one proxied completion).

### Stage 4 — Sandbox, queue, harnesses
- **Docker sandbox manager**: two-phase lifecycle (PREP bridge → sealed `internal:true` network, Tension 1); fresh container per run; hardening flags above; stdout/stderr + exit state capture with **max_output_bytes truncation, log size bounds, and retention/GC policy for data/ artifacts**; docker-stats resource metrics; auto cleanup.
- **Queue**: asyncio worker behind an interface; persistent state machine (spec §13 states); idempotency keys; pause (= **stop scheduling new runs only**, v1) / resume / cancel (kills container) / retry; **crash reconciliation (2A)**: every container labeled `run_id`, startup sweep kills orphans and transitions stale RUNNING/PREPARING → FAILED(crash, retryable); heartbeat timestamps. **Single-scheduler enforcement**: queue worker starts only in one process (guard against uvicorn multi-worker/reload spawning duplicate schedulers).
- **Artifact consistency**: atomic file writes (tmp+rename), checksum in DB, finalization step, orphan file cleanup in the reconciliation sweep.
- **HarnessAdapter ABC** + registry. Implement:
  - **FakeHarness** — deterministic patch on the fixture repo, and it **must exercise the real protocol**: calls the proxy (FakeProvider behind it) and acts on the response, so demo runs cover proxy + adapter plumbing.
  - **mini-SWE-agent adapter** (real, in-container per 3A): consult current official docs, pin versions; subprocess/CLI mode if the Python API is unstable, same normalized result + telemetry contract.
- Preflight compatibility check (spec §21) on the tiny fixture.

### Stage 5 — Tasks and evaluation
- User-defined tasks (§8.1); historical-commit replay (§8.2, 1–5 manually selected).
- Hidden-test candidate extractor (conservative, §10): diff test files base→target, confidence marking, user approve/reject; **reject candidates importing implementation that only exists in the target commit**; provenance recorded.
- **Fresh-container evaluation (Tension 2)**: patch applied to clean snapshot in evaluator-owned container. Evaluators: Build, ExistingTests, HiddenTests, Regression, Lint, TypeCheck, PatchStats, ProhibitedFiles, Efficiency, ReliabilityAggregator — all consuming the shared parser layer (4A). **Regression comparison by stable test-case identity** (baseline case set vs post-patch case set), with explicit rules for flaky/collection-failure/timeout/changed-inventory cases — never bare exit codes.
- `INSUFFICIENT_EVALUATION_SIGNAL` marking. Raw evaluator results and normalized scores stored separately.
- Experiment matrix, preview count, live SSE events, failure categorization via ErrorCategory.

### Stage 6 — Results, recommendations, frontend screens
- Reliability aggregation per combination (success rate, mean/median/stddev, timeout/empty-patch/crash rates). **Statistical honesty**: at default 3 reps, display spread without significance claims; flag statistically weak results per spec §17.
- Eligibility rules + default weights (50/20/15/10/5); efficiency normalized within task **with a documented caveat that within-task normalization is cohort-relative** (adding a bad combination shifts scores); **defined aggregation rules across tasks** (missing runs, timeouts, insufficient-signal tasks excluded per documented policy, not silently averaged).
- Four recommendation cards with why-it-won, trade-offs, confidence, weakness flags; Pareto frontiers (correctness vs tokens, vs duration).
- Frontend screens per spec §20: Dashboard, onboarding wizard (5 steps), task selection, experiment config (matrix preview), live experiment (SSE), results, run detail. No secrets rendered.

### Stage 7 — Fixture, tests, docs
- `fixtures/python-bug-repo`: FastAPI app with seeded bug, existing tests, one historical-like commit, one hidden test. `make seed` / `make demo` — full demo with FakeHarness+FakeProvider (exercising the proxy), zero API cost.
- Docs per spec §27 incl. Mermaid architecture + data model, leakage-prevention explanation, security-limitations warning (Docker ≠ hardened multi-tenant isolation), scoring methodology, extension guides. `docs/implementation-plan.md` mirrors this plan.

## Test requirements (6A — written alongside features, not deferred)

Planned from the start (unit): detection, command detection, scoring, reliability aggregation, model filtering, provider-error normalization, leakage prevention, hidden-test extraction, state transitions; integration: experiment creation, queue with FakeHarness, proxy with FakeProvider, Docker sandbox with fixture (skip w/o Docker). Frontend: config matrix, result cards, failure states, API mocking, Playwright smoke (repo → task → experiment → mocked completion → results).

Added by review (the 12 gaps):
1. **[→E2E, CRITICAL]** AGENT-phase container cannot reach the internet, CAN reach only the proxy (proves 1A/Tension 1).
2. **[→E2E]** Crash reconciliation: kill backend mid-run → restart sweeps orphan container, marks run FAILED(crash), retry works (2A).
3. **[→E2E]** Cancel ACTIVE run → container actually terminates.
4. Proxy budget/spend-ceiling exhaustion mid-run → run fails with clear category, experiment continues.
5. Run-token expiry: post-completion reuse rejected; renewal path for long runs.
6. Idempotency: duplicate dispatch of the same run rejected.
7. Shared parser fixtures: pytest/vitest outputs incl. skipped/xfail/collection-error/parse-error; baseline-vs-post identity comparison.
8. Repo size limit + path traversal rejection; clone hardening cases.
9. Wizard: edited command persists and is used by baseline.
10. Baseline partially failing → warn-and-proceed flow.
11. Pause → resume mid-experiment; RATE_LIMITED → retry flow.
12. Results: INSUFFICIENT_EVALUATION_SIGNAL rendering; empty-patch surfaced not scored.

Test plan artifact for /qa: `~/.gstack/projects/evalHarness/swastik.methi-no-branch-eng-review-test-plan-20260729.md`.

## NOT in scope (considered and deferred)

- OpenHands + smolagents real integrations — next pass; adapter ABC accommodates them (registry stubs also dropped from pass 1, Tension 4).
- PR replay beyond stub; differential testing; generated tests; reviewer-model evaluation — interfaces + TODO docs only (spec §11).
- Compose packaging of the backend (socket mount + path translation) — TODOS.md (Tension 3).
- Submodule/LFS repository support — explicit rejection with clear error instead (Codex batch).
- TypeScript fixture repo — only if time permits (spec §22).
- Ollama/vLLM/Groq/etc. providers — ABC ready.
- Auth, multi-tenancy, billing, cloud sandboxes, Kubernetes (spec §2 exclusions).
- Premise-#1 falsification study (~15 users, <30% bar) — product task tracked in the design doc, not an engineering stage.

## What already exists (reuse over rebuild)

- Greenfield repo: no internal code to reuse. External reuse: mini-SWE-agent (agent loop — wrapped, not rebuilt), OpenRouter's OpenAI-compatible API (no custom client protocol), Alembic/SQLAlchemy/pytest (no bespoke infra), Docker SDK (no shell-string container management). The spec's interface sketches (§3, §4, §15) are adopted as-is.

## Failure modes (per new codepath)

| Codepath | Realistic failure | Test? | Handled? | User-visible? |
|---|---|---|---|---|
| PREP→AGENT network switch | container keeps egress after switch | E2E #1 | fail-closed: verify before agent start | clear run failure |
| Proxy budgets | runaway agent loops requests | #4 | hard ceiling + ErrorCategory | run fails, experiment continues |
| Queue crash | orphan container + stale RUNNING | E2E #2 | reconciliation sweep (2A) | run shows FAILED(crash), retryable |
| Patch apply in evaluator | patch doesn't apply to clean snapshot | unit | counted as agent failure, categorized | run detail shows apply error |
| Parser on weird output | collection error mistaken for 0 tests | #7 | identity-based comparison + explicit parse-error state | evaluation confidence lowered |
| Free-tier 429 storms | experiment stalls | #11 | RATE_LIMITED state + backoff retry | live screen shows rate-limit warnings |
| SQLite contention | database-is-locked under SSE+worker | integration | WAL + busy_timeout + batching (7A) | none (prevented) |

No critical gaps remain: every identified silent-failure path now has a test and error handling.

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| S1 Foundation + skeleton | backend/app/*, frontend/src/*, Makefile | — |
| S2 Repo analysis + baseline | repositories/, sandboxes/exec, evaluators/parsers | S1 |
| S3 Provider + proxy | providers/, api/proxy | S1 |
| S4 Sandbox + queue + harness | sandboxes/, orchestration/, harnesses/ | S1 (uses S3 proxy for real harness) |
| S5 Tasks + evaluation | tasks/, evaluators/ | S2, S4 |
| S6 Results + UI | scoring/, frontend/src/* | S5 |
| S7 Fixture + docs | fixtures/, docs/ | S6 |

Lanes: after S1 → **Lane A: S2**, **Lane B: S3** in parallel (disjoint modules). S4 follows (needs both for the real-harness path; FakeHarness part can start alongside S3). Then sequential S5 → S6 → S7. Conflict flag: S2 and S4 both touch `sandboxes/` — S2 owns `sandboxes/exec` only; coordinate that boundary.

## Implementation Tasks

Synthesized from review findings. P1 blocks ship; P2 same branch; P3 follow-up.

- [ ] **T1 (P1, human: ~1d / CC: ~30min)** — sandboxes — Implement two-phase network lifecycle (PREP bridge → internal-only) with fail-closed verification. Surfaced by: Architecture #1 + Tension 1. Files: `backend/app/sandboxes/manager.py`. Verify: E2E test #1.
- [ ] **T2 (P1, human: ~1d / CC: ~30min)** — orchestration — run_id container labels + startup reconciliation sweep + heartbeats. Surfaced by: Architecture #2. Files: `backend/app/orchestration/queue.py`, `recovery.py`. Verify: E2E test #2.
- [ ] **T3 (P1, human: ~1d / CC: ~30min)** — harnesses/sandbox-images — mini-SWE-agent bundled in sandbox image; env-injected proxy URL + token. Surfaced by: Architecture #3. Files: `sandbox-images/python/Dockerfile`, `backend/app/harnesses/mini_swe_agent.py`. Verify: preflight check on fixture.
- [ ] **T4 (P2, human: ~0.5d / CC: ~15min)** — core — shared CommandResult exec layer + test-output parsers with case identity. Surfaced by: Code Quality #4. Files: `backend/app/sandboxes/exec.py`, `backend/app/evaluators/parsers/`. Verify: parser fixture tests (#7).
- [ ] **T5 (P2, human: ~2h / CC: ~10min)** — core — ErrorCategory enum + per-layer mappers. Surfaced by: Code Quality #5. Files: `backend/app/core/errors.py`. Verify: provider-error normalization tests.
- [ ] **T6 (P1, human: ~2-3d / CC: ~1-2h)** — tests — implement the 12 gap tests alongside their features. Surfaced by: Test review #6. Files: `backend/tests/`, `frontend/tests/`. Verify: `make test` green incl. E2E #1-3.
- [ ] **T7 (P2, human: ~1h / CC: ~5min)** — db — WAL + busy_timeout + single-writer + event batching. Surfaced by: Performance #7. Files: `backend/app/db/engine.py`. Verify: SSE+worker integration test, no lock errors.
- [ ] **T8 (P1, human: ~1d / CC: ~30min)** — evaluators — fresh-container patch-apply evaluation; ProhibitedFiles gate on test/CI paths. Surfaced by: Tension 2. Files: `backend/app/evaluators/runner.py`. Verify: tampering fixture (agent deletes a test) is caught.
- [ ] **T9 (P1, human: ~0.5d / CC: ~15min)** — providers — hard per-run/per-experiment spend ceilings + routing-metadata recording + usage-estimation fallback. Surfaced by: Tension 5. Files: `backend/app/providers/proxy.py`. Verify: budget exhaustion test (#4).
- [ ] **T10 (P2, human: ~1d / CC: ~30min)** — hardening batch — single-scheduler guard, thread-isolated Docker calls, log bounds/GC, atomic artifacts, UID mapping, clone hardening, container flags, pause=stop-scheduling, token renewal, stats caveats, aggregation rules, deterministic-vs-live release gates. Surfaced by: Tension 5 (17 notes). Files: spread per stage. Verify: respective unit/integration tests.

## Verification

- `make setup && make dev` (native backend + vite) starts; `/api/v1/health`, `/ready` OK.
- End of Stage 1: walking-skeleton FakeHarness run visible via API.
- `make test` green at every stage boundary (deterministic gate); `make demo` runs the fixture experiment end-to-end with recommendations rendered.
- Live smoke (separate, optional gate): real mini-SWE-agent × pinned `:free` model on the fixture repo completes in Docker under spend ceiling; tokens/cost recorded; AGENT-phase container demonstrably offline except the proxy.
- Playwright smoke passes.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 7 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CODEX:** Outside voice ran (codex, high effort) — 33 findings; 5 cross-model tensions resolved (two-phase sandbox, fresh-container evaluation, native-host dev backend, walking-skeleton sequencing, 17-note hardening batch all accepted); remainder folded as stage requirements.
- **CROSS-MODEL:** Claude review and Codex agree on the final architecture; Codex's scope critique ("core loop is months of work") was noted but scope was a settled user decision (design doc D11) and was not reopened.
- **VERDICT:** ENG CLEARED — ready to implement.

NO UNRESOLVED DECISIONS
