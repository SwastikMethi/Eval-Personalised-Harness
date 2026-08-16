---
tags: [aso/reference, aso/constraint]
status: current
updated: 2026-08-11
---

# Rate Limits

Index: [[00 Index]]. Decision that flows from this: [[ADR-003 Free Tier Constraints]].

## This account

```sh
curl -s -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/key
```

Returned on 2026-08-11:

```
is_free_tier      True
limit             None
usage             0
limit_remaining   None
rate_limit        {'requests': -1, ...  'deprecated and safe to ignore'}
```

The `rate_limit` field is deprecated and tells you nothing. The useful fact is **`is_free_tier: true`** with no credits purchased.

## Documented free-tier policy

- ~**20 requests/minute**
- ~**50 free-model requests/day** with no credits ever purchased
- ~**1000/day** once ≥$10 of credits has been purchased (the balance need not be spent)

Treat these as approximate — measure real consumption during [[Milestones]] Milestone A rather than trusting the numbers.

## What this costs in practice

An experiment is `tasks × harnesses × models × repetitions`, and each run makes many model requests.

| Matrix | Runs | @8 req/run | Free-tier days |
|---|---|---|---|
| 2×3×1 task×1 rep | 6 | 48 | 1 |
| 2×3×1 task×3 reps | 18 | 144 | ~3 |
| 2×3×2 tasks×3 reps | 36 | 288 | ~6 |

## How the system must behave

1. **429 → `RATE_LIMITED`, never `FAILED`.** Currently broken — [[Known Defects]] #6. Exponential backoff, re-queue, renew the run token.
2. **Persist across restarts.** A parked run resumes cleanly; the queue already persists state.
3. **Surface consumption** before exhaustion, not after.
4. **Never crash the experiment** — [[Acceptance Criteria]] #24.

## Development rule

**Use `FakeProvider` for everything except milestone runs.** `make demo` and the whole test suite run at zero quota. Burning the daily cap on a debugging loop costs a day of wall-clock.

## Provider error handling required (§4)

Handle and normalize: HTTP **402**, **429**, **5xx**, timeout, invalid response, context-limit. Record provider rate-limit headers when available.

## Related

- [[Free Models]] · [[Model Proxy]] · [[Run Lifecycle]] · [[Milestones]]
