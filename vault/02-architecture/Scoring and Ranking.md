---
tags: [aso/architecture]
status: current
updated: 2026-08-11
---

# Scoring and Ranking

Source: `generationDoc.md` §16, §17. Implemented in `app/scoring/aggregate.py`. Index: [[00 Index]].

## Eligibility comes first

Do not hide all results behind one score. A combination is **ineligible** for the balanced recommendation when it:

- never produces a patch
- consistently fails a required build
- introduces critical regressions
- falls below the hidden-test threshold
- times out in more than half its runs
- has insufficient evaluation signal
- completes fewer than the configured minimum repetitions

## Default weights

| Dimension | Weight |
|---|---|
| Correctness | 50% |
| Reliability | 20% |
| Execution efficiency | 15% |
| Token efficiency | 10% |
| Resource efficiency | 5% |

Efficiency is normalized **within each task cohort** (documented caveat: cohort-relative) and **gated by correctness**.

> **Fast-but-wrong must never win.** Avoid rewarding a combination merely because it stopped early without completing the task. This is a §31 hard rule, not a tuning preference.

## Reliability

Per harness-model-task combination: success rate, mean score, median score, standard deviation, timeout rate, empty-patch rate, harness crash rate, model-provider failure rate, test-result variance.

> A single lucky run must not dominate the recommendation.

Failure categories must stay distinguishable: model failure · harness failure · repository/setup failure · provider rate limiting · evaluation failure · agent-produced incorrect solution.

## Outputs

Four recommendations — **best quality**, **best reliability**, **best efficiency**, **best balanced** — each showing why it won, trade-offs, confidence, task count, completed repetitions, correctness, reliability, average duration, average tokens, failure rate, and whether the result is statistically weak.

Plus Pareto-frontier analysis for correctness vs. tokens and correctness vs. duration.

## Statistical honesty

Under the configured minimum (3) completed repetitions, results are flagged **statistically weak**. No significance claims from a small experiment — §17 and §31 both forbid it.

This is why [[Milestones]] treats repetitions as worth the quota cost: with 1 rep, every result is flagged weak by design.

## Related

- [[Evaluation Engine]] · [[Milestones]] · [[Product Goal]]
