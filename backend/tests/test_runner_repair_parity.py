"""The baseline and the evaluator must measure the same machine.

`Pokemon-Battle-Simulator` declares mcp, pandas, requests and pydantic, and
never mentions pytest. The baseline noticed, installed it, and reported five
test cases. Grading did not, so `pytest -v` died in 55 ms with nothing to
parse — and the three tests that passed at baseline looked like they had
vanished, which was recorded as three regressions, which supplied a 0.0 score
and made the run look measured. Two harnesses were then ranked against each
other on a 0.0 vs 0.0 tie.

So two properties, and the second matters as much as the first:
  1. grading repairs a missing runner exactly as the baseline does;
  2. when a suite genuinely cannot run, that is reported as no signal, never as
     "every test regressed".
"""

from pathlib import Path

from app.evaluators.engine import (
    INSUFFICIENT_EVALUATION_SIGNAL,
    EvaluationContext,
    evaluate,
)
from app.evaluators.runner_repair import install_command, looks_like_missing_runner
from app.sandboxes.exec import CommandResult

PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1 +1 @@\n"
    "-VALUE = 1\n"
    "+VALUE = 2\n"
)

BASELINE = [
    ("test_suite.py::test_one", "passed"),
    ("test_suite.py::test_two", "passed"),
]


def snapshot(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text("VALUE = 1\n")
    (root / "test_suite.py").write_text(
        "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n"
    )


def result(command: str, *, code: int, out: str = "", err: str = "") -> CommandResult:
    return CommandResult(command=command, exit_code=code, stdout=out, stderr=err, duration_s=0.05)


# --- detection --------------------------------------------------------------


def test_a_missing_runner_is_told_apart_from_failing_tests() -> None:
    missing = result("pytest -v", code=1, err="No module named pytest")
    assert looks_like_missing_runner(missing, "pytest")

    real_failures = result("pytest -v", code=1, out="test_x.py::test_a FAILED")
    assert not looks_like_missing_runner(real_failures, "pytest")

    assert install_command("pytest") == "python -m pip install pytest"
    assert install_command(None) is None


# --- parity -----------------------------------------------------------------


def test_grading_installs_a_missing_runner_and_then_collects_cases(tmp_path: Path) -> None:
    """The direct regression test for the measured 0.0. Before the fix the
    evaluator had no repair, so this scenario yielded zero cases."""
    source = tmp_path / "base"
    snapshot(source)
    installed: list[str] = []

    def execute(command: str, cwd: Path, **kwargs: object) -> CommandResult:
        if "pip install pytest" in command:
            installed.append(command)
            return result(command, code=0)
        if installed:  # runner present now
            return result(
                command,
                code=0,
                out="test_suite.py::test_one PASSED\ntest_suite.py::test_two PASSED",
            )
        return result(command, code=1, err="/usr/local/bin/python: No module named pytest")

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "python -m pytest -v"},
            test_framework="pytest",
            baseline_cases=BASELINE,
        ),
        tmp_path / "work",
        execute=execute,
    )

    assert installed, "the evaluator never tried to install the missing runner"
    existing = outcome.results["existing_tests"]
    assert existing["runner_installed"] is True
    assert existing["scoreable_cases"] == 2
    assert outcome.results["regressions"]["count"] == 0
    assert outcome.score == 1.0


# --- a dead suite is not a regression ---------------------------------------


def test_a_suite_that_cannot_run_reports_no_signal_not_regressions(tmp_path: Path) -> None:
    """The false-confidence half. Zero cases plus unreadable output must not be
    read as "both baseline tests regressed" — that is what made a 0.0 look like
    a measurement and let a winner be picked from it."""
    source = tmp_path / "base"
    snapshot(source)

    def broken(command: str, cwd: Path, **kwargs: object) -> CommandResult:
        # Fails in a way the repair cannot help with, so no cases ever appear.
        return result(command, code=2, err="ImportError: cannot import name 'thing'")

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "python -m pytest -v"},
            test_framework="pytest",
            baseline_cases=BASELINE,
        ),
        tmp_path / "work",
        execute=broken,
    )

    existing = outcome.results["existing_tests"]
    assert existing["suite_failed"] is True
    assert outcome.results["regressions"]["count"] == 0
    assert outcome.results["regressions"]["not_computed"] is True
    assert outcome.signal == INSUFFICIENT_EVALUATION_SIGNAL
    assert outcome.score is None, "a suite that never ran must not yield a score"


def test_the_failing_output_is_kept_so_it_can_be_diagnosed(tmp_path: Path) -> None:
    """Diagnosing the real incident took a manual `docker run`, because the
    evaluator recorded an exit code and threw the output away."""
    source = tmp_path / "base"
    snapshot(source)

    def broken(command: str, cwd: Path, **kwargs: object) -> CommandResult:
        return result(command, code=2, err="ImportError: cannot import name 'thing'")

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "python -m pytest -v"},
            test_framework="pytest",
        ),
        tmp_path / "work",
        execute=broken,
    )
    assert "ImportError" in outcome.results["existing_tests"]["output"]
