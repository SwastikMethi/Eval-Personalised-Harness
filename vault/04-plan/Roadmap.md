---
tags: [aso/plan]
status: current
updated: 2026-08-11
---

# Roadmap

Phases 0–11 plus two milestones. Index: [[00 Index]]. Full plan: `.claude/plans/steady-coalescing-lighthouse.md`.

**Ordering principle:** reach a *real* 2-harness × 3-model run as early as possible, because that is the first thing that proves the product works. Everything not on that critical path comes after [[Milestones]] Milestone A.

| Phase | What | Status |
|---|---|---|
| 0 | Knowledge base — this vault + `CLAUDE.md` | ✅ |
| 1 | Repair foundations — Alembic, seed, frontend test infra | ✅ |
| 2 | **Wire the golden path** — snapshot, commands, baseline cases | ✅ |
| 3 | **Proxy hardening** — rate limits, tool calls, cost | ⬜ |
| 4 | smolagents harness | ⬜ |
| ▶ | **Milestone A — 6-run smoke test** | ⬜ |
| 5 | Preflight and compatibility (§21) | ⬜ |
| 6 | Evaluator ABC refactor (§15) | ⬜ |
| 7 | Complete data model (§18) | ⬜ |
| 8 | SSE + remaining API (§19) | ⬜ |
| 9 | Five missing screens (§20) | ⬜ |
| ▶ | **Milestone B — scaled matrix** | ⬜ |
| 10 | OpenHands harness | ⬜ |
| 11 | Remaining spec surface | ⬜ |

---

## Phase 0 — Knowledge base
This vault + root `CLAUDE.md`, so every session starts with context instead of re-deriving it.

## Phase 1 — Repair foundations
- `alembic init`, point at `app.core.config.settings`, autogenerate initial migration, **stamp** (not apply) against existing `data/aso.db`, replace implicit `create_all`
- `app/seed.py` per §22
- `vitest` + `@testing-library/react` + `jsdom` + `msw`, real `test` script

**Verify:** `make migrate`, `make seed`, `make test` exit 0 *and do something*.

## Phase 2 — Wire the golden path
Fixes [[Known Defects]] #1, #2, #3.
- `queue.py::_execute` — resolve repo, call `create_snapshot(root, task.base_commit, workspace)`; keep `fixture_path` fallback so the fake demo works
- `queue.py::_evaluate` — same resolution, so grading uses a fresh snapshot at base
- `routes.py::create_experiment` — `RepositoryCommand` → `config["commands"]`, `BaselineResult` → `config["baseline_cases"]`; explicit request values win

**Verify:** a `from-commit` run builds via `create_snapshot`; workspace has one synthetic commit, no remotes; solution commit absent.

## Phase 3 — Proxy hardening
Fixes #4, #5, #6. **Highest value** — quota is the binding constraint.
- 429 → `RATE_LIMITED` + exponential backoff + re-queue (not `FAILED`); renew token
- `max_model_requests` default **8**; surface per-run consumption
- Real pricing into `issue_run_token()`
- `tools`/`tool_choice`/`stream` on `ChatRequest`; return provider's real `choices`

**Verify:** all against `FakeProvider`, zero quota spent.

## Phase 4 — smolagents harness
- Pin `smolagents` in `sandbox-images/python/Dockerfile`
- `app/harnesses/smolagents_agent.py` following the `mini_swe_agent.py` in-container pattern
- Register in `main.py`; add to `SANDBOXED_HARNESSES`
- **Never fabricate token counts** — leave `None`, let proxy metrics be truth

## Phase 5 — Preflight (§21)
Static checks + live preflight (edit one file in a tiny fixture, verify patch). Block or warn-with-acknowledgement.

## Phase 6 — Evaluator ABC (§15)
Refactor to ten composable evaluators, preserving behaviour and tests. `Lint` and `TypeCheck` are new.

## Phase 7 — Data model (§18)
Six missing tables + migration; persist harness/sandbox metrics and recommendations.

## Phase 8 — SSE + API (§19)
`GET /experiments/{id}/events` plus preview-matrix, cancel-experiment, recommendations, run-detail set, PR metadata.

## Phase 9 — Frontend (§20)
Onboarding wizard, task selection, experiment config with matrix preview, results screen (4 cards + Pareto via Recharts), run detail. Component tests. Never render secrets.

## Phase 10 — OpenHands
Last by design — it wants its own Docker runtime, forbidden by our socket-less [[Sandbox]]. Try local/CLI runtime on a separate image; fall back to a subprocess adapter preserving the telemetry contract. Requires Phase 3.

## Phase 11 — Remaining spec
PR replay, `docker-compose.yml`, diagnostics page, Playwright, TS fixture + node image, §27 docs.

## Per-phase verification loop (§29)

```sh
make lint && make typecheck && make test
make demo          # fake harness, zero cost, still green
```

Then update [[Acceptance Criteria]] and append to [[Session Log]].

## Related

- [[Milestones]] · [[Known Defects]] · [[Spec Gaps]] · [[ADR-003 Free Tier Constraints]]
