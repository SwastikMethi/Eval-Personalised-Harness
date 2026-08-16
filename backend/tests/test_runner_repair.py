"""A missing test runner must not decide whether a repo can be scored.

Pokemon-Battle-Simulator returned repo_tests with 5 parsed cases once, and
unbenchmarkable an hour later, on identical input — because the analysing model
happened to write "&& pip install pytest" the first time and not the second.
The verdict cannot depend on a model remembering to install the runner.

Behind it sat a worse defect: parse_generic synthesises one case from an exit
code, so "sh: pytest: not found" counted as a test case and could satisfy the
repo_tests rung. A runner that never ran must never look like a working suite.
"""

from pathlib import Path

from app.repositories.baseline import BaselineOutcome, run_baseline
from app.repositories.strategy import REPO_TESTS, UNBENCHMARKABLE, decide_strategy
from app.sandboxes.exec import CommandResult

PYTEST_OUTPUT = """\
test_battle.py::test_attack PASSED
test_battle.py::test_faint PASSED

============================== 2 passed in 0.10s ===============================
"""


def result(cmd: str, code: int, out: str = "") -> CommandResult:
    return CommandResult(command=cmd, exit_code=code, stdout=out, stderr="", duration_s=0.1)


def test_missing_runner_is_installed_and_the_suite_reruns(tmp_path: Path) -> None:
    seen: list[str] = []

    def execute(cmd: str, workspace: Path) -> CommandResult:
        seen.append(cmd)
        if "pip install pytest" in cmd:
            return result(cmd, 0, "Successfully installed pytest")
        if "pytest" in cmd:
            # First attempt has no runner; after the install it works.
            if any("pip install pytest" in c for c in seen[:-1]):
                return result(cmd, 0, PYTEST_OUTPUT)
            return result(cmd, 1, "/usr/local/bin/python: No module named pytest")
        return result(cmd, 0)

    outcome = run_baseline(
        tmp_path, {"install": "pip install -r requirements.txt", "test": "python -m pytest -v"},
        "pytest", execute,
    )

    assert outcome.benchmarkable
    assert outcome.repaired
    assert len(outcome.test_cases) == 2, "the suite ran once the runner was present"
    assert "test_before_repair" in outcome.steps, "the original failure stays on record"


def test_the_missing_dependency_is_reported_as_a_repo_change(tmp_path: Path) -> None:
    """The user asked to be told what the repo needs — and it must be a
    suggestion, never a write into their repository."""

    def execute(cmd: str, workspace: Path) -> CommandResult:
        if "pip install pytest" in cmd:
            return result(cmd, 0)
        if "pytest" in cmd and "install" not in cmd:
            return result(cmd, 1, "No module named pytest")
        return result(cmd, 0)

    outcome = run_baseline(tmp_path, {"test": "python -m pytest"}, "pytest", execute)

    assert outcome.suggested_repo_changes
    change = outcome.suggested_repo_changes[0]
    assert change["file"] == "requirements.txt"
    assert change["add"] == "pytest"
    assert "why" in change


def test_genuine_test_failures_are_not_treated_as_a_missing_runner(tmp_path: Path) -> None:
    """A suite that runs and reports failures is a legitimate baseline."""
    calls: list[str] = []

    def execute(cmd: str, workspace: Path) -> CommandResult:
        calls.append(cmd)
        return result(cmd, 1, "test_x.py::test_a FAILED\n=== 1 failed in 0.1s ===")

    outcome = run_baseline(tmp_path, {"test": "python -m pytest"}, "pytest", execute)

    assert not outcome.repaired
    assert not any(
        "pip install pytest" in c for c in calls
    ), "must not reinstall over a real failure"


# --- the fabrication guard --------------------------------------------------


def test_an_exit_code_case_does_not_satisfy_repo_tests() -> None:
    """parse_generic's synthetic ("__command__", failed) case is not evidence.

    Observed for real: a baseline recorded benchmarkable=True with cases=1 whose
    only "case" came from `sh: 1: pytest: not found`.
    """
    fabricated = BaselineOutcome(
        benchmarkable=True,
        warn=False,
        steps={"test": {"exit_code": 127, "parse_ok": False}},
        test_cases=[("__command__", "failed")],
    )
    decision = decide_strategy(
        {"test": "pytest -v", "install": None, "build": None},
        "generic",
        commit_test_count=0,
        run_baseline=lambda: fabricated,
    )
    assert decision.strategy == UNBENCHMARKABLE
    assert any("no parseable case" in a.reason for a in decision.attempts if not a.ok)


def test_parsed_cases_still_satisfy_repo_tests() -> None:
    real = BaselineOutcome(
        benchmarkable=True,
        warn=False,
        steps={"test": {"exit_code": 0, "parse_ok": True}},
        test_cases=[("t::a", "passed"), ("t::b", "failed")],
    )
    decision = decide_strategy(
        {"test": "pytest -v", "install": None, "build": None}, "pytest", 0, lambda: real
    )
    assert decision.strategy == REPO_TESTS
