---
tags: [aso/product, aso/status]
status: current
updated: 2026-08-11
---

# Acceptance Criteria

Source: `generationDoc.md` §30. Index: [[00 Index]].

**Live tally: 21 pass · 3 partial · 1 fail.** Update this note as phases land — it is the single scoreboard for "is the MVP done".

> Baseline at the start of this work was **17 pass · 4 partial · 4 fail**. (An earlier draft of this note said 15/5/5; that was a miscount of the table below.) Phase 2 moved #10 ❌→✅ and #11 ⚠️→✅; Phase 3 moved #24 ❌→✅.

| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Start the application locally with documented commands | ✅ | `make setup` / `make dev` |
| 2 | Configure an OpenRouter API key | ✅ | `.env`, never logged |
| 3 | Fetch available exact free model variants | ✅ | `GET /providers/openrouter/models` |
| 4 | Select up to three pinned models | ✅ | snapshot endpoint pins exact IDs |
| 5 | Add a local or public Git repository | ✅ | submodule/LFS rejected |
| 6 | Detect Python or JS/TS build and test commands | ✅ | pluggable detectors |
| 7 | Edit detected commands | ✅ | `PUT /repositories/{id}/commands` |
| 8 | Run a clean baseline | ✅ | per-test-case results stored |
| 9 | Select a historical commit as a task | ✅ | `POST /tasks/from-commit` |
| 10 | Agent receives only the base repository snapshot | ✅ | Phase 2 — `materialize_workspace` snapshots at `base_commit` |
| 11 | Final historical patch not available inside the sandbox | ✅ | Phase 2 — asserted by `test_golden_path.py` (no solution file, one commit, no remotes) |
| 12 | Select OpenHands, mini-SWE-agent, and smolagents | ⚠️ | Phase 4 added smolagents — 2 of 3. OpenHands is Phase 10, see [[ADR-001 Harness Choice]] |
| 13 | Validates harness-model compatibility | ❌ | No preflight subsystem (§21) |
| 14 | Each run executes in a fresh Docker container | ✅ | non-root, cap-drop ALL, limits |
| 15 | Runs queued with configurable concurrency | ✅ | semaphore, default 1 |
| 16 | Every combination can run multiple repetitions | ✅ | idempotency keys per rep |
| 17 | Existing tests run after the agent completes | ✅ | fresh-snapshot evaluation |
| 18 | Eligible hidden tests run after completion | ✅ | conservative extraction + approval |
| 19 | Records tokens, time, commands, patch stats, tests, failures | ⚠️ | Harness/sandbox metrics collected but never persisted — no `HarnessMetric`/`SandboxMetric` tables |
| 20 | View live progress | ✅ | Phase 8 — SSE stream replays persisted events, with a polling fallback |
| 21 | Compare combinations | ✅ | comparison table + aggregation |
| 22 | Best quality/reliability/efficiency/balanced recommendations | ✅ | 4 cards, Pareto frontiers |
| 23 | Weak evaluation signal clearly identified | ✅ | `INSUFFICIENT_EVALUATION_SIGNAL` |
| 24 | Provider rate limiting does not crash the experiment | ✅ | Phase 3 — 429 → `RATE_LIMITED` with persisted escalating backoff, then `PENDING` |
| 25 | Automated tests and a working fixture demo | ⚠️ | 77 backend tests pass; **zero** frontend tests, `make test-frontend` is a false green |

## Which phase fixes what

| Criterion | Fixed by |
|---|---|
| 10, 11 | [[Roadmap]] Phase 2 — wire the golden path |
| 24 | Phase 3 — rate-limit survival |
| 12 | Phase 4 (smolagents) and Phase 10 (OpenHands) |
| 13 | Phase 5 — preflight |
| 19 | Phase 7 — data model completion |
| 20 | Phase 8 — SSE |
| 25 | Phase 1 (test infra) and Phase 9 (component tests) |

## Related

- [[Known Defects]] · [[Spec Gaps]] · [[Roadmap]]
