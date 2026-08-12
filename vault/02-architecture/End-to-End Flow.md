---
tags: [aso/architecture]
status: current
updated: 2026-08-12
---

# End-to-End Flow — every stage and the tech behind it

One pass from *"here is my repo"* to *"use this stack"*, naming the technology
at each stage and **why that one**. For the state machine see [[Run Lifecycle]];
for the safety argument see [[Leakage Prevention]], [[Model Proxy]], [[Sandbox]].

> **Reading this as a stack story:** the whole system is one FastAPI process on
> port 8005 plus one SQLite file plus Docker. Everything else is a library
> choice inside that. The infrastructure that is *absent* — no Redis, no Celery,
> no Postgres, no Kubernetes — is a deliberate constraint (spec §31): a
> single-user local tool must be startable with `make dev` and debuggable by
> reading one process.

---

## Stage 0 — The shell everything runs in

| Concern | Choice | Why |
|---|---|---|
| API | **FastAPI 0.115** | Async-native, so a request can await Docker and upstream models without blocking; Pydantic validation comes free with the framework. |
| Server | **uvicorn** on **:8005**, bound `0.0.0.0` | ASGI for the async stack. The bind is load-bearing, not cosmetic: sandboxed agents reach the proxy through Docker's host gateway, which cannot see `127.0.0.1`. See [[Known Defects]]. |
| Config | **pydantic-settings 2** | One typed `Settings` object from env + `.env`, so a missing key is a startup error rather than a `None` three layers down. |
| Process model | **Native host process, not containerised** | The backend must drive the Docker socket to create sandboxes. Containerising it would mean mounting `docker.sock` into a container — the exact thing forbidden for sandboxes. See [[ADR-004 Backend on Host]]. |

---

## Stage 1 — Repository ingestion

**What happens:** a local path or GitHub URL is registered; a GitHub repo is
cloned once into `data/repos/<id>` and reused thereafter.

| Concern | Choice | Why |
|---|---|---|
| VCS | **git CLI via `subprocess`** | The operations needed (`clone`, `archive`, `rev-list`, `diff --name-only`) are exactly what the CLI does well. A binding like `pydulwich`/`GitPython` would add a dependency for no capability gain. |
| Concurrency | **per-repo `threading.Lock`** | Clone-once/reuse-after. Previously every call re-cloned, racing the backgrounded baseline against the tree it was reading. |
| Storage | **`data/` on disk (gitignored)** | Repos and artifacts are large and disposable; the database stores paths, not blobs. |

---

## Stage 2 — Task definition

Two kinds, per spec §8:

- **Commit replay** — pick a real commit; the repo is rewound to its **parent**
  and the agent is asked to implement the change.
- **User-defined** — a written task with an explicit base commit.

| Concern | Choice | Why |
|---|---|---|
| Prompt construction | `tasks/historical.py::commit_task_description()` | The commit message is carried verbatim (spec §8.2) but **reframed as work to do**. Raw commit messages are past-tense descriptions of finished work, and agents replied "this has been added" and stopped. |
| Leakage guard | changed file **paths only, never diff hunks** | Paths orient the agent; the diff would hand over the answer and reduce the benchmark to transcription. A test asserts a sentinel from the real fix never appears in the prompt. |

---

## Stage 3 — Experiment definition (the matrix)

**What happens:** the user picks harnesses × models × config; the cartesian
product becomes `ExperimentCombination` rows, each expanded into `repetitions`
`BenchmarkRun` rows in `PENDING`.

| Concern | Choice | Why |
|---|---|---|
| ORM | **SQLAlchemy 2** (typed `Mapped[...]`) | Declarative models that mypy can check; the run state machine is worth having typed. |
| Database | **SQLite in WAL mode** | Single-user, single-writer, zero-admin. WAL lets the UI poll while the worker writes. Postgres would add a service to install for no benefit at this scale. |
| Migrations | **Alembic** | Schema grows per stage; migrations keep an existing `data/aso.db` usable across upgrades. |
| Idempotency | unique `idempotency_key` per (combination, repetition) | Re-submitting an experiment must not silently double the work or the spend. |

---

## Stage 4 — Scheduling

| Concern | Choice | Why |
|---|---|---|
| Queue | **in-process `asyncio` worker** (`orchestration/queue.py`) | The whole system is one process; a task queue (Celery/RQ) would add a broker, a second process, and a serialization boundary to run *one job at a time* on a laptop. |
| Concurrency | `asyncio.Semaphore`, default **1** | Runs compete for Docker, CPU and provider quota. Serial execution keeps timing measurements comparable — a benchmark whose runs interfere measures the wrong thing. |
| Backoff | persisted `retry_after` + escalating `(30s, 120s, 600s)` | Survives a restart. At ~50 free requests/day, throttling is the ordinary path, not an edge case. |
| Crash recovery | startup `reconcile()` | Marks stale `PREPARING`/`RUNNING` rows `FAILED(crash)` and removes orphaned containers. ⚠️ It sweeps **every** `aso.run_id` container, so starting a second backend kills live runs. |

---

## Stage 5 — Workspace materialization ← **the leakage boundary**

**What happens:** `git archive` at the **base** commit into a fresh directory,
then `git init` plus one synthetic commit.

| Concern | Choice | Why |
|---|---|---|
| Snapshot | **`git archive`**, not `clone`/`checkout` | `archive` exports a *tree*, carrying no history. A clone would bring the solution commit, future history and the origin remote into the sandbox — the agent could simply read the answer, or fetch it. |
| New history | `git init` + one commit | The agent still gets a working git repo (harnesses expect one) and `git diff` still yields a patch, but there is nothing to diff *against* except its own work. |

This stage is why the benchmark means anything. See [[Leakage Prevention]].

---

## Stage 6 — Prepared image

**What happens:** the repo's dependency install runs **once** at image build
time, producing `aso-prepared:<repo>-<manifest-hash>`, reused by every run in
the matrix.

| Concern | Choice | Why |
|---|---|---|
| Build | **Docker image layered `FROM` the sandbox base** | A 6-cell matrix would otherwise repeat the same `pip install` six times. Baking it in turns per-run setup into a no-op. |
| Cache key | hash of the dependency **manifests** | Changing `requirements.txt` must rebuild; editing source must not. |
| Base image | `python:3.12-slim` + git + Node 20 + pinned harnesses | Node is present because spec §6 makes JS/TS first-class — a JS repo cannot be baselined without npm. |

---

## Stage 7 — Sandbox: two-phase network

| Phase | Network | Why |
|---|---|---|
| **PREP** | default bridge, internet reachable | Dependency install and baseline need the network. The agent is **not** running yet. |
| **AGENT** | `internal: true`, bridge disconnected | Internal networks have no default route, so general egress is dead. |

| Concern | Choice | Why |
|---|---|---|
| Isolation | **Docker**, `cap_drop: ALL`, `no-new-privileges`, non-root uid 1000, pids/memory/CPU caps | Reproducible environments and a real filesystem/network boundary. ⚠️ This is *isolation for honest measurement*, **not** a claim of hardened protection against hostile code. |
| No `docker.sock` | never mounted | Mounting it would hand the agent control of the host daemon and void every other control. A harness needing it does not ship. |
| Proxy reachability | **relay container** straddling both networks | An internal network has no route to the host gateway either, so `host.docker.internal` dies with egress. The relay is the agent's single reachable destination. |
| Fail-closed | seal verifies egress is dead **and** the proxy answers over HTTP | Verifying only the first is how a run silently made zero model requests and still looked successful. |

---

## Stage 8 — Model access

**What happens:** the run gets a short-lived token; the agent's OpenAI-compatible
client points at the relay, which forwards to the proxy on the host.

| Concern | Choice | Why |
|---|---|---|
| Indirection | **run-scoped proxy** (`api/proxy.py`) | The container **never** receives the real API key — only a per-run token that expires, is pinned to one model, and carries request/token/spend ceilings. |
| Client | **httpx** (async), timeout from `provider_timeout_seconds` (600s) | Same async stack as FastAPI. The timeout is configurable because reasoning models routinely think for minutes; a hardcoded 120s turned a slow model into 10 consecutive 502s. |
| Providers | **OpenRouter** and **NVIDIA NIM**, both OpenAI-compatible | One request shape, two providers, chosen per combination. See [[ADR-002 Model Selection]]. |
| Accounting | one `ModelRequestMetric` row per request | The authoritative spend record: it survives retries and restarts, where the in-memory token counter reports only the latest attempt. |
| Zero-cost path | **FakeProvider** | Development and the full test suite cost no quota. |

---

## Stage 9 — Harness execution

Both harnesses run **inside** the sandbox (eng review 3A) so their shell and
code execution is jailed and their only network path is the relay.

| Harness | Version | Shape |
|---|---|---|
| **smolagents** | 1.26.0 | `CodeAgent` — writes and executes Python. Currently the only one to produce patches. |
| **mini-SWE-agent** | 1.14.0 | CLI agent driving shell commands via litellm. |

| Concern | Choice | Why |
|---|---|---|
| Adapter boundary | `HarnessAdapter` → `HarnessRunResult` | Every harness normalizes to one result shape, so the orchestrator holds **no** harness-specific logic (spec §31). |
| Unavailable metrics | reported **`null`**, never `0` | `commands_executed` is meaningless for a CodeAgent, and an unreadable trajectory is not "zero steps". A fabricated zero would distort the comparison. |
| Patch extraction | `git add -A && git diff --cached` | The synthetic history from Stage 5 makes the diff exactly the agent's work. |

---

## Stage 10 — Evaluation

**What happens:** the patch is applied to a fresh snapshot and the repo's tests
run **in a container**, compared against a pre-recorded baseline.

| Concern | Choice | Why |
|---|---|---|
| Fresh snapshot | new workspace, not the agent's | The agent may have left the tree dirty or broken; grading must judge the patch, not the debris. |
| Baseline diff | pass/fail per test **vs. baseline** | Repos have pre-existing failures. Absolute counts would score the repo, not the agent. |
| Hidden tests | never in the sandbox | Otherwise the agent optimizes against the grader. |
| Honest abstention | `INSUFFICIENT_EVALUATION_SIGNAL` | A repo with no runnable tests **cannot** be scored. Emitting a number anyway would be the most damaging thing this tool could do. |

---

## Stage 11 — Scoring and ranking

Weights (`scoring/aggregate.py`): **correctness 50 · reliability 20 · execution
efficiency 15 · token efficiency 10 · resource efficiency 5**.

| Concern | Choice | Why |
|---|---|---|
| Correctness dominates | 50% | It is the point. Everything else is a tiebreak among things that work. |
| Efficiency gated behind correctness | eligibility rules | Otherwise a harness that fails instantly wins on speed and cost. |
| Similarity to the real patch | **diagnostic only, zero weight** | Many valid solutions differ from what the author wrote; scoring resemblance would reward mimicry. |
| Trade-offs | **Pareto frontiers** | "Best" differs by priority; a single ranking hides combinations that win on one axis. |
| Statistics | plain Python | With ~3 repetitions there is nothing to be significant. Claiming significance would be false precision. |

---

## Stage 12 — The dashboard

| Concern | Choice | Why |
|---|---|---|
| UI | **React 19 + TypeScript + Vite 8** | Typed contracts against the API; Vite for fast iteration. |
| Components | **MUI 9** | Dense data tables and forms out of the box; this is an instrument panel, not a brand surface. |
| Server state | **TanStack Query 5** | Polling, caching and invalidation for live run status — hand-rolled `useEffect` polling is where duplicated requests and stale panels come from. |
| Charts | **Recharts 3** | Pareto and comparison plots from React components. |
| Tests | **Vitest + Testing Library + MSW** | MSW mocks at the network layer, so components are tested against realistic API responses. |

---

## Cross-cutting toolchain

| Tool | Role | Why |
|---|---|---|
| **uv** | Python env + runner | Fast, lockfile-based, reproducible. |
| **ruff** | lint + import order | One fast tool replacing flake8/isort/pyupgrade. |
| **mypy --strict** | type checking | Typed layers are what keep provider/harness/sandbox/evaluator independent. |
| **pytest** (+ `docker` marker) | tests | The marker exists because container-creating tests **destroy a live benchmark run** — use `pytest -m "not docker"` while one is in flight. |
| **Make** | entry points | `make dev`, `make test`, `make demo`. See [[Make Targets]]. |

---

## The flow in one line

```
repo → task (base commit) → matrix → queue → git archive snapshot → prepared image
     → container (PREP: net) → seal (AGENT: no net, relay only) → run token
     → harness in sandbox → model via proxy → patch → evaluate in container
     → score → aggregate → recommend
```

Related: [[System Overview]] · [[Run Lifecycle]] · [[Leakage Prevention]] ·
[[Model Proxy]] · [[Sandbox]] · [[Evaluation Engine]] · [[Scoring and Ranking]] ·
[[Codebase Map]]
