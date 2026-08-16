---
tags: [aso/status]
status: current
updated: 2026-08-11
---

# Implemented

**Verified by reading code and running tests on 2026-08-11** — not copied from README claims. Index: [[00 Index]].

## Verified working

| Area | Detail |
|---|---|
| Backend skeleton | FastAPI, SQLAlchemy 2, SQLite WAL, structured JSON logging, `/health` + `/ready` |
| Repository analysis | Python + JS/TS detectors, editable commands, submodule/LFS rejection, size limit |
| Baseline validation | Snapshot at HEAD, install/build/test, **per-test-case** results stored |
| OpenRouter provider | Exact free-variant pinning, error normalization, rate-limit header capture, `openrouter/free` banned |
| Model proxy | Run-token auth, model pinning, request/token/spend budgets, per-request metrics |
| Docker sandbox | Fresh non-root container, cpu/mem/pids limits, cap-drop ALL, two-phase network with fail-closed egress probe |
| Queue | 9-state machine with validated transitions, idempotency keys, crash reconciliation, cancel/retry/pause/resume |
| Historical commit replay | Leakage-proof snapshot builder, conservative hidden-test extraction with approval |
| Evaluation | Fresh-snapshot patch apply, prohibited-file gate, identity-based regressions, `INSUFFICIENT_EVALUATION_SIGNAL` |
| Scoring | 50/20/15/10/5 weights, eligibility rules, Pareto frontiers, 4 recommendation cards |
| Tests | **77 backend tests, all passing in ~9s** |

## Counts

| Thing | Have | Spec wants |
|---|---|---|
| Harnesses | 1 real (mini-SWE-agent) + fake | 3 |
| Providers | OpenRouter + fake | 1 for MVP ✅ |
| DB tables | 14 | 19 |
| Frontend screens | 2 | 7 |
| Frontend tests | 0 | component + Playwright |

## The important caveat

The hard, easy-to-get-wrong parts are genuinely built: leakage prevention, proxy isolation, the state machine, fail-closed sealing. What is missing is mostly **breadth** — plus a handful of wiring defects that mean **the system has never run a real benchmark**. It can only run the bundled fixture with a fake harness and fake provider.

See [[Known Defects]] for what blocks a real run, and [[Spec Gaps]] for what the spec asks for that does not exist.

## Related

- [[Known Defects]] · [[Spec Gaps]] · [[Acceptance Criteria]] · [[Codebase Map]]
