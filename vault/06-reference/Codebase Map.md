---
tags: [aso/reference]
status: current
updated: 2026-08-11
---

# Codebase Map

File → responsibility. ~4,100 lines of source. Index: [[00 Index]].

## Backend

| Path | Lines | Responsibility |
|---|---|---|
| `app/orchestration/queue.py` | 361 | **Queue worker, state machine, run pipeline.** The heart. See [[Run Lifecycle]] |
| `app/orchestration/recovery.py` | 71 | Crash reconciliation on startup |
| `app/scoring/aggregate.py` | 233 | Reliability, ranking, Pareto, recommendations. See [[Scoring and Ranking]] |
| `app/evaluators/engine.py` | 207 | Patch grading on a fresh snapshot. See [[Evaluation Engine]] |
| `app/evaluators/parsers.py` | 92 | Test-output parsing → per-case results |
| `app/sandboxes/manager.py` | 195 | Docker lifecycle, two-phase network, `seal()`. See [[Sandbox]] |
| `app/sandboxes/exec.py` | 68 | Command result type, output limits |
| `app/api/proxy.py` | 195 | **Run-scoped model proxy.** See [[Model Proxy]] |
| `app/providers/openrouter.py` | 193 | OpenRouter provider, free-variant detection, error normalization |
| `app/providers/base.py` / `fake.py` | 50 / 50 | Provider contract + zero-cost fake |
| `app/api/repos_analysis.py` | 191 | Analyze, baseline, commits — **only caller of `create_snapshot`** |
| `app/api/routes.py` | 187 | Repos, tasks, experiments, runs |
| `app/api/tasks_api.py` | 104 | Commit tasks, hidden-test approval |
| `app/api/results_api.py` | 103 | Results and recommendations |
| `app/api/run_control.py` | 59 | Cancel, retry, pause, resume |
| `app/api/providers_api.py` | 51 | Model listing, snapshot pinning |
| `app/repositories/detectors.py` | 145 | Python / JS-TS language + command detection |
| `app/repositories/service.py` | 132 | Registration, cloning, **`create_snapshot`**. See [[Leakage Prevention]] |
| `app/repositories/baseline.py` | 72 | Baseline validation |
| `app/tasks/historical.py` | 101 | Commit replay + hidden-test extraction |
| `app/harnesses/base.py` | 81 | `HarnessAdapter` contract + registry |
| `app/harnesses/mini_swe_agent.py` | 111 | **The one real harness.** Pattern to copy for smolagents |
| `app/harnesses/fake.py` | 88 | Fake harness exercising the real proxy protocol |
| `app/models/` | ~250 | 14 SQLAlchemy tables (spec wants 19 — see [[Spec Gaps]]) |
| `app/demo.py` | 78 | `make demo` — full fake experiment |

## Frontend

| Path | Lines | Responsibility |
|---|---|---|
| `src/pages/ExperimentDetail.tsx` | 208 | Live run progress |
| `src/pages/Dashboard.tsx` | 83 | Recent repos/experiments |
| `src/api.ts` | 79 | Typed client |

Five screens missing — see [[Spec Gaps]].

## Elsewhere

| Path | Purpose |
|---|---|
| `sandbox-images/python/Dockerfile` | `aso-sandbox-python:dev`; pins `mini-swe-agent==1.14.0` |
| `fixtures/python-bug-repo/` | Demo fixture: `median()` bug + tests |
| `generationDoc.md` | **Original spec** — preserved unchanged |
| `docs/architecture.md` | As-built writeup (superseded by this vault) |
| `docs/implementation-plan.md` | Reviewed build plan |
| `data/` | SQLite DB + run artifacts (gitignored) |

## Entry points for common changes

| To change… | Start at |
|---|---|
| How a run executes | `queue.py::_execute` |
| How a patch is graded | `evaluators/engine.py::evaluate` |
| How workspaces are built | `repositories/service.py::create_snapshot` |
| Add a harness | `harnesses/base.py` + `main.py` registration + `SANDBOXED_HARNESSES` |
| Add a provider | `providers/base.py::ModelProvider` |
| Model budgets/pinning | `api/proxy.py` |

## Related

- [[System Overview]] · [[Known Defects]] · [[Make Targets]]
