---
tags: [aso/decision]
status: accepted
date: 2026-08-15
supersedes: "the measurement-honesty rule forbidding historical-patch similarity as a correctness metric"
---

# ADR-005 — Judged diff accuracy for commit tasks

## Status

**Accepted, 2026-08-15.** Reverses a previously locked decision. Recorded here so the
reversal is findable rather than folklore.

## What changed

`CLAUDE.md` §4 stated:

> Do not use historical-patch similarity as a correctness metric — diagnostic only, zero weight.

For commit-replay tasks, an analyzer model (gpt-5.6-sol) may now compare the agent's patch to
the real commit and that comparison **contributes to the correctness score**.

## Why the original rule existed

Because a correct fix written differently from the original is not a wrong fix. Rewarding
resemblance to one particular author's solution measures conformity, not correctness — and an
agent that solved the problem more cleanly would be marked down for it.

That reasoning has not been refuted. It is being traded away deliberately.

## Why it is being traded

Every route to an execution-based correctness signal on real repositories has failed in
practice, and each failure was in the repository's test infrastructure rather than in the
agents:

- Three of `Pokemon-Battle-Simulator`'s five tests have `pass` as their entire body, so they
  cannot distinguish a correct patch from an empty one. The other two fail before an agent
  touches anything.
- Its commits ship no tests, so nothing can be extracted from the diff.
- Generated tests are verifiable but not reliably generatable: the same commit produced a
  passing verified test in the morning and three rejected attempts in the afternoon, because
  the analyzer cannot be pinned to temperature 0 (see [[Known Defects]] #17).
- The graded container lacked the test runner entirely, so grading returned 0.0 for every
  agent regardless of its work.

A metric with a known bias is more useful than no metric. The bias is stated below rather
than hidden, and the raw comparison stays visible so a score can be argued with.

## The cost, stated plainly

**A genuinely correct fix that differs from the original commit will score low.** This is not
an edge case; it is the expected behaviour of the metric. Two consequences follow:

1. A judged-diff score is evidence about *similarity*, and only indirectly about correctness.
2. When tests produce real signal, they are the better measure. Correctness is therefore the
   **mean of the test score and the judged-diff score when both exist**, and whichever exists
   alone otherwise. Both are reported separately so the number can be taken apart.

## What would reverse this again

Repositories whose own suites produce genuine signal, or generated tests that verify
reliably. If either arrives, judged-diff accuracy should return to diagnostic-only. The
comparison is worth keeping in the report either way — it is genuinely informative to see how
an agent's approach differed from the original author's.

## Not affected

- Theory tasks, which are graded against a grounded rubric and never against a diff.
- The prohibition on the agent's patch touching tests, config or CI (`PROHIBITED_PATTERNS`).
- Every other measurement-honesty rule in `CLAUDE.md` §4, which stand unchanged — in
  particular "do not produce a winner from weak evaluation signal", which this ADR makes
  *more* important, not less.

Related: [[Known Defects]] · [[Evaluation Engine]] · [[Scoring and Ranking]]
