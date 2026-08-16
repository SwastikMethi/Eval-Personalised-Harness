"""Decide how a repository can be evaluated at all (spec §11).

The user should not have to know which fallback applies to their repo. A model
proposes commands and a strategy; this module **verifies the proposal by
executing it** and walks down the ladder until something produces real signal:

    1  commit_tests    tests the historical commit itself adds
    2  repo_tests      the repository's own suite
    3  build_only      build / static checks
    -  unbenchmarkable nothing above produced signal

Rungs 4-6 of the spec ladder (differential checks, generated tests,
reviewer-model grading) are deliberately absent: this module configures the
benchmark, it never judges a patch.

**The model proposes; the container decides.** A strategy is adopted because it
ran and produced signal, never because a model asserted it would. That
distinction is the whole point — `Ai-Web-Scraper` produced two real patches and
no score, and no amount of confident analysis would have changed that. Saying
`unbenchmarkable` up front is the honest outcome, and is more useful than a
fabricated one.

No network and no Docker in here: the caller supplies the model's suggestion
and a `run_baseline` callable, so the ladder itself stays unit-testable.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.repositories.baseline import BaselineOutcome

COMMIT_TESTS = "commit_tests"
REPO_TESTS = "repo_tests"
BUILD_ONLY = "build_only"
UNBENCHMARKABLE = "unbenchmarkable"

# What each strategy actually licenses us to claim, shown to the user before
# any credits are spent. build_only must never read as correctness.
STRATEGY_MEANING = {
    COMMIT_TESTS: (
        "Graded against the tests the chosen commit itself adds. Strongest available "
        "signal: those tests describe the behaviour the change was meant to produce."
    ),
    REPO_TESTS: (
        "Graded against the repository's own suite, compared with a baseline so "
        "pre-existing failures are not charged to the agent."
    ),
    BUILD_ONLY: (
        "Graded only on whether the build still passes. This is a WEAK signal: it "
        "shows a patch did not break the build, not that it did the right thing."
    ),
    UNBENCHMARKABLE: (
        "No runnable check was found, so patches cannot be verified. Runs will "
        "report INSUFFICIENT_EVALUATION_SIGNAL and no winner will be declared."
    ),
}


@dataclass
class RungAttempt:
    rung: int
    strategy: str
    ok: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyDecision:
    strategy: str
    commands: dict[str, str | None]
    test_framework: str | None
    attempts: list[RungAttempt] = field(default_factory=list)
    # Which model chose the commands, so an odd decision is traceable
    # (spec §10: record provenance, never assume trustworthiness).
    provenance: dict[str, str] = field(default_factory=dict)
    warn: bool = False
    # Things the REPO needs for its own suite to run. Shown to the user and
    # never written — this tool measures a repository, it does not edit one.
    suggested_repo_changes: list[dict[str, str]] = field(default_factory=list)

    @property
    def scoreable(self) -> bool:
        return self.strategy != UNBENCHMARKABLE

    @property
    def meaning(self) -> str:
        return STRATEGY_MEANING[self.strategy]


def _step_ok(outcome: BaselineOutcome, step: str) -> bool:
    record = outcome.steps.get(step)
    return record is not None and record.get("exit_code") == 0


def _has_real_test_cases(outcome: BaselineOutcome) -> bool:
    """Cases that came from a framework parser, not from an exit code.

    `parse_generic` synthesises a single ("__command__", failed) case from the
    exit status alone, so `sh: pytest: not found` counted as "1 test case" and
    could satisfy this rung. Grading a matrix against a runner that never ran
    is precisely the fabrication this ladder exists to prevent, so the cases
    must be backed by `parse_ok`.
    """
    if not outcome.test_cases:
        return False
    record = outcome.steps.get("test") or {}
    return bool(record.get("parse_ok"))


def decide_strategy(
    commands: dict[str, str | None],
    test_framework: str | None,
    commit_test_count: int,
    run_baseline: Callable[[], BaselineOutcome] | None,
    provenance: dict[str, str] | None = None,
) -> StrategyDecision:
    """Walk the ladder, verifying each rung by execution.

    `run_baseline` is invoked at most ONCE — it already reports install, build
    and test in a single pass, so re-running it per rung would pay for the same
    container three times.
    """
    attempts: list[RungAttempt] = []
    decision = StrategyDecision(
        strategy=UNBENCHMARKABLE,
        commands=commands,
        test_framework=test_framework,
        provenance=provenance or {},
    )

    has_commands = any(commands.get(k) for k in ("install", "build", "test"))
    outcome = run_baseline() if (run_baseline and has_commands) else None
    if outcome is not None:
        decision.warn = outcome.warn
        decision.suggested_repo_changes = list(outcome.suggested_repo_changes)

    # Rung 1 — tests the commit brings with it. Cheapest and strongest, but the
    # environment must still be able to run them, so a failed install
    # disqualifies it exactly as it would disqualify the repo's own suite.
    install_broken = outcome is not None and not _step_ok(outcome, "install") and (
        "install" in outcome.steps
    )
    if commit_test_count > 0 and not install_broken:
        attempts.append(
            RungAttempt(
                1, COMMIT_TESTS, True, f"{commit_test_count} test file(s) added by the commit",
                {"commit_test_files": commit_test_count},
            )
        )
        decision.strategy = COMMIT_TESTS
        decision.attempts = attempts
        return decision

    attempts.append(
        RungAttempt(
            1,
            COMMIT_TESTS,
            False,
            "dependency install failed, so extracted tests could not run"
            if install_broken
            else "no commit in range adds or modifies test files",
            {"commit_test_files": commit_test_count},
        )
    )

    # Rung 2 — the repository's own suite. Requires parsed cases: a test command
    # that errors out with nothing readable is silence, not a passing suite.
    if outcome is None:
        attempts.append(RungAttempt(2, REPO_TESTS, False, "no test command to verify"))
    elif outcome.benchmarkable and _has_real_test_cases(outcome):
        repaired = " after installing the missing runner" if outcome.repaired else ""
        attempts.append(
            RungAttempt(
                2, REPO_TESTS, True,
                f"{len(outcome.test_cases)} test case(s) parsed{repaired}",
                {"test_cases": len(outcome.test_cases), "repaired": outcome.repaired},
            )
        )
        decision.strategy = REPO_TESTS
        decision.attempts = attempts
        return decision
    else:
        attempts.append(
            RungAttempt(
                2,
                REPO_TESTS,
                False,
                "the test command produced no parseable case — the runner may not have run"
                if outcome.benchmarkable
                else "baseline did not complete (install, build or collection failed)",
                {"test_cases": len(outcome.test_cases), "steps": sorted(outcome.steps)},
            )
        )

    # Rung 3 — build only. Weak, and labelled as such wherever it is shown.
    if outcome is not None and _step_ok(outcome, "build"):
        attempts.append(RungAttempt(3, BUILD_ONLY, True, "build succeeded on the base commit"))
        decision.strategy = BUILD_ONLY
        decision.attempts = attempts
        return decision

    attempts.append(
        RungAttempt(
            3,
            BUILD_ONLY,
            False,
            "no build command" if not commands.get("build") else "build failed on the base commit",
        )
    )
    decision.attempts = attempts
    return decision
