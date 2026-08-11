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
