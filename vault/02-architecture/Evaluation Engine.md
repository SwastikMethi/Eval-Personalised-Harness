---
tags: [aso/architecture, aso/invariant]
status: current
updated: 2026-08-11
---

# Evaluation Engine

Source: `generationDoc.md` §11, §15. Implemented in `app/evaluators/engine.py`. Index: [[00 Index]].

## The integrity rule

**Grading never happens in the agent's workspace.** The only agent input to grading is the **patch**, applied to a fresh snapshot and run with evaluator-owned commands. An agent cannot influence its own grade by editing the test runner, the fixtures, or the environment.

## Pipeline

```
patch → prohibited-file gate → apply to fresh snapshot
      → visible tests → hidden tests → regression check
      → signal + score
```

| Step | Rule |
|---|---|
| **Prohibited files** | Patches touching test files, CI config, or Makefiles score **zero** |
| **Apply** | Fresh snapshot at the base commit, not the agent's directory |
| **Visible tests** | Tests that existed at the base commit |
| **Hidden tests** | Extracted from the target commit, user-approved, run only after the agent stops |
| **Regressions** | Per-test-case **identity** comparison against baseline — a *vanished* test counts as a regression |

Failures already present at the base commit are never counted as agent-introduced regressions.

## Insufficient signal

When no deterministic evaluator exists, the task is marked:

```
INSUFFICIENT_EVALUATION_SIGNAL
```

and produces **no winner**. §31: *do not generate a winner when evaluation confidence is insufficient.*

## Fallback order for repos without tests (§11)

1. Tests added by the historical commit/PR ✅
2. Build and static-analysis checks ✅
3. User-defined evaluation commands ✅
4. Differential behaviour checks — *interface + TODO only*
5. Generated tests — *interface + TODO only*
6. Reviewer-model evaluation — low-weight supplemental only

Items 4–6 must not pretend to be complete.

## Never do this

> Do not use textual similarity to the historical patch as the primary correctness metric.

Similarity may appear as optional diagnostic information with **zero weight** in the default score.

## Current shape vs. spec

§15 asks for a composable `Evaluator` ABC with ten named evaluators. Today this is a **single `evaluate()` function** plus module-level helpers, and `Lint`/`TypeCheck` evaluators do not exist. Behaviour is correct; the architecture is not. Refactor is [[Roadmap]] Phase 6.

## MVP caveat

Evaluator commands execute **on the host** against the fresh snapshot (same trust level as baseline validation). Moving evaluation into a fresh container is the next hardening step. See [[Sandbox]].

## Related

- [[Leakage Prevention]] · [[Scoring and Ranking]] · [[Spec Gaps]]
