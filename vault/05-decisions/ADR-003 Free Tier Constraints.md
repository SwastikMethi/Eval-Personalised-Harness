---
tags: [aso/adr, aso/constraint]
status: accepted
date: 2026-08-11
updated: 2026-08-11
---

# ADR-003 — Quota, not money, sets the schedule

Index: [[00 Index]]. **Read this before planning any real run.**

## Context

All three pinned models are free ([[ADR-002 Model Selection]]), so cost is $0. But OpenRouter's free tier caps **requests**, and this account has purchased no credits:

- ~**20 requests/minute**
- ~**50 free-model requests/day** without credits

An experiment is `tasks × harnesses × models × repetitions`, and each run makes many model requests. Quota, not engineering speed, becomes the schedule driver.

## The arithmetic

| Requests/run | 6-run smoke | Fits one day? |
|---|---|---|
| 8 | 48 | Yes, barely |
| 25 | 150 | No — 3 days |
| 50 (old default) | 300 | No — 6 days |

## Decision

1. **`max_model_requests` defaults to 8** for [[Milestones]] Milestone A.
2. **Rate-limit survival is load-bearing, not hardening.** [[Roadmap]] Phase 3 must land before any real run. Without it, hitting the cap mid-matrix writes spurious `FAILED` rows that corrupt results — see [[Known Defects]] #6.
3. **Develop against `FakeProvider`.** All unit tests, integration tests, and `make demo` use fakes. Real quota is spent only on milestone runs.
4. **Milestone B spreads across days** rather than shrinking below 3 repetitions, because [[Scoring and Ranking]] flags anything under 3 reps as statistically weak.

## Consequences

- The queue's persistence and backoff are now correctness features, not conveniences. A run parked by `RATE_LIMITED` must resume cleanly after a restart.
- Per-run request consumption must be **visible** before quota is exhausted, not discovered afterwards.
- A full 36-run matrix is a multi-day exercise. Plan around it; do not try to force it into one session.

## Superseded in part (2026-08-12)

A second provider now exists — see [[ADR-005 Second Provider]]. "Quota sets the schedule" was true while OpenRouter was the only option; with NVIDIA NIM selectable per combination, a matrix can be split across providers or run entirely on the one with headroom. The mechanics below still hold (budgets, backoff, develop-against-`FakeProvider`), because NIM credits are finite too — but the six-day estimate for a 36-run matrix no longer follows.

## The escape hatch, stated honestly

Roughly **$10 of credits raises the cap to ~1000 requests/day**, turning the full matrix into a single afternoon. This is worth knowing, not a recommendation — the plan assumes it does not happen and works regardless.

## Related

- [[Rate Limits]] · [[Free Models]] · [[Milestones]] · [[Known Defects]]
