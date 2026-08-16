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

## Where evaluator commands run

**In a container**, as of 2026-08-12. Previously they ran on the host, which was both a weaker trust boundary — evaluation executes the *agent's patch* — and a correctness bug: `pip` and the test runner resolved independently, so on a machine with two Pythons install wrote to one interpreter while the tests ran under another. Install reported success having installed nothing the tests could see. See [[Known Defects]] #16.

Dependencies are installed **once per repo** into a prepared image (`aso-prepared:<repo>-<manifest hash>`), reused by the baseline, every evaluation, and every agent run. The install command still runs inside the container — normally a no-op, but it picks up a dependency an agent's patch adds, which is what makes the cache safe.

Still on the default bridge network: installs need egress, and unlike the agent sandbox there is no model to isolate from. Sealing evaluation after the install phase remains a possible later step.

## Related

- [[Leakage Prevention]] · [[Scoring and Ranking]] · [[Spec Gaps]]
