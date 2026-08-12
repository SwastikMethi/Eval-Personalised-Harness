"""The evaluation strategy is decided by execution, not by assertion.

A model proposing "run pytest" means nothing if pytest parses zero cases — that
is the exact shape that let Ai-Web-Scraper produce two real patches and no
score. The ladder must verify each rung and fall through honestly, ending at
unbenchmarkable rather than inventing signal.
"""

from app.repositories.baseline import BaselineOutcome
from app.repositories.strategy import (
    BUILD_ONLY,
    COMMIT_TESTS,
    REPO_TESTS,
    UNBENCHMARKABLE,
    decide_strategy,
)

CMDS = {"install": "pip install -r requirements.txt", "test": "pytest -v", "build": None}


def baseline(**kw):  # type: ignore[no-untyped-def]
    defaults = {"benchmarkable": True, "warn": False, "steps": {}, "test_cases": []}
    return lambda: BaselineOutcome(**{**defaults, **kw})


def test_commit_tests_wins_when_the_commit_brings_tests() -> None:
    d = decide_strategy(CMDS, "pytest", commit_test_count=2, run_baseline=baseline())
    assert d.strategy == COMMIT_TESTS
    assert d.scoreable
    assert d.attempts[0].ok and d.attempts[0].rung == 1


def test_repo_suite_used_when_the_commit_has_no_tests() -> None:
    d = decide_strategy(
        CMDS,
        "pytest",
        commit_test_count=0,
        run_baseline=baseline(test_cases=[("t1", "passed"), ("t2", "failed")]),
    )
    assert d.strategy == REPO_TESTS
    assert [a.ok for a in d.attempts] == [False, True]


def test_a_proposed_suite_that_parses_nothing_does_not_become_repo_tests() -> None:
    """The anti-fabrication case. The model said "pytest -v"; pytest produced no
    readable case, so this is silence and must not be graded against."""
    d = decide_strategy(
        {**CMDS, "build": "python -m compileall -q ."},
        "pytest",
        commit_test_count=0,
        run_baseline=baseline(
            benchmarkable=False,
            test_cases=[],
            steps={"build": {"exit_code": 0}, "test": {"exit_code": 1}},
        ),
    )
    assert d.strategy == BUILD_ONLY, "must fall to the next rung, never claim repo_tests"
    assert any(a.strategy == REPO_TESTS and not a.ok for a in d.attempts)


def test_nothing_runnable_is_reported_as_unbenchmarkable() -> None:
    d = decide_strategy(
        {"install": None, "test": None, "build": None},
        None,
        commit_test_count=0,
        run_baseline=baseline(),
    )
    assert d.strategy == UNBENCHMARKABLE
    assert not d.scoreable
    assert "INSUFFICIENT_EVALUATION_SIGNAL" in d.meaning


def test_broken_install_disqualifies_commit_tests() -> None:
    """Extracted tests still need an environment to run in — claiming
    commit_tests here would fail later, during grading, where it is expensive."""
    d = decide_strategy(
        CMDS,
        "pytest",
        commit_test_count=3,
        run_baseline=baseline(benchmarkable=False, steps={"install": {"exit_code": 1}}),
    )
    assert d.strategy != COMMIT_TESTS
    assert "install failed" in d.attempts[0].reason


def test_build_only_is_labelled_weak() -> None:
    d = decide_strategy(
        {"build": "npm run build", "test": None, "install": None},
        None,
        commit_test_count=0,
        run_baseline=baseline(steps={"build": {"exit_code": 0}}),
    )
    assert d.strategy == BUILD_ONLY
    assert "WEAK" in d.meaning, "a weak signal must announce itself as one"


def test_provenance_is_recorded() -> None:
    d = decide_strategy(
        CMDS, "pytest", 1, baseline(), provenance={"provider": "anthropic", "model": "claude-x"}
    )
    assert d.provenance["provider"] == "anthropic"


def test_baseline_is_run_at_most_once() -> None:
    calls = []

    def once() -> BaselineOutcome:
        calls.append(1)
        return BaselineOutcome(benchmarkable=True, warn=False, steps={}, test_cases=[])

    decide_strategy(CMDS, "pytest", 0, once)
    assert len(calls) == 1, "one container is enough to verify every rung"
