---
tags: [aso/plan]
status: current
updated: 2026-08-11
---

# Milestones

The two points where the product either works or does not. Index: [[00 Index]].

---

## ▶ Milestone A — 6-run smoke test

**2 harnesses × 3 models × 1 task × 1 rep** against `fixtures/python-bug-repo`.

| Setting | Value |
|---|---|
| Harnesses | mini-SWE-agent, smolagents |
| Models | see [[ADR-002 Model Selection]] |
| `max_model_requests` | **8** |
| Total request budget | 6 × 8 = **48** — fits one free-tier day |
| Cost | $0 (all models free) |

**Prerequisites:** Phases 1–4. Phase 3 especially — without `RATE_LIMITED` handling, hitting the cap mid-run writes spurious `FAILED` rows.

### Pass criteria

Every cell reaches `COMPLETED` **or** fails with a *correctly categorized* error. Then confirm:

- [ ] Patches produced where expected
- [ ] Usage recorded per run (`ModelRequestMetric` rows)
- [ ] Sealed-network probe passed for every run
- [ ] No OpenRouter key in any container env
- [ ] Workspace contained one synthetic commit, no remotes, no solution commit

**This is the first real proof the product works.**

### Status 2026-08-11: pipeline proven, no solve yet

Live runs against real models now work end to end. What is confirmed:

| Evidence | Result |
|---|---|
| Real model requests through the sealed sandbox | ✅ up to **20 requests/run** |
| Real token accounting | ✅ **27,166 in / 4,222 out** on one run |
| Agent executes real shell commands | ✅ **14 steps, 14 commands** |
| Network isolation under load | ✅ egress refused, relay only |
| Budget enforcement | ✅ `budget_exhausted` fires at the cap |
| Both harnesses reach the model | ✅ mini-SWE-agent and smolagents |
| **A passing patch** | ❌ **not yet** |

Two distinct reasons no combination has solved the task yet, both informative rather than defects:

1. **Budget.** mini-SWE-agent spends most of its steps exploring; at 8 requests it was still reading files, and at 20 it was still running the test suite. The task needs more budget than free tier comfortably allows.
2. **Harness × model incompatibility.** `cohere/north-mini-code:free` returns tool-call JSON where smolagents expects `<code>` blocks → "Error in code parsing". This is exactly the signal the product exists to surface, and exactly what spec §21 preflight ([[Roadmap]] Phase 5) is for.

Also learned: `openai/gpt-oss-20b:free` is heavily throttled upstream — **4 consecutive 429s before one success**.

### On empty patches

The fixture bug (`median()` wrong on even-length lists) is a one-line fix, so 8 requests is fair. If models exhaust the budget without patching, that is a **legitimate benchmark result** the eligibility rules should mark — not something to paper over. §31: *do not fake metrics.*

---

## ▶ Milestone B — scaled matrix

Repetitions are the point: reliability, variance, and the "statistically weak" flag only mean something with repeated runs. See [[Scoring and Ranking]].

**The problem:** 2 tasks × 3 reps × 6 combinations = **36 runs ≈ 288 requests ≈ 6 free-tier days** at 8 requests/run.

### Two routes — choose once Milestone A gives real per-run numbers

| Route | Shape | Cost in days |
|---|---|---|
| **Spread** | all 36 runs, across several days | ~6 |
| **Shrink** | 1 task × 3 reps = 18 runs | ~3 |

Spreading is safe: the queue persists state across restarts, and `RATE_LIMITED` backoff parks runs automatically when quota is exhausted. Nothing is lost.

Then repeat against the real repository (named at run time).

> The daily cap is the schedule driver, **not** engineering effort. See [[ADR-003 Free Tier Constraints]].

## Related

- [[Roadmap]] · [[Rate Limits]] · [[ADR-002 Model Selection]] · [[Acceptance Criteria]]
