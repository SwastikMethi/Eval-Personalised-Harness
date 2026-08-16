"""Tests that cannot fail must not vote on quality.

A test whose body is `pass` succeeds for a correct patch and an empty one
alike. Three of them in a five-case suite is how an agent scored 0.6 for
editing a README: the two real tests were already failing and so excluded as
pre-existing, leaving nothing behind the correctness number.

They are excluded from the SCORE only. Regression counting still watches them,
because a test that could not fail and now does means the agent broke
collection — which is the damage that check exists to catch.
"""

from pathlib import Path

from app.evaluators.engine import (
    INSUFFICIENT_EVALUATION_SIGNAL,
    EvaluationContext,
    _case_name,
    evaluate,
)
from app.repositories.detectors import vacuous_test_names
from app.sandboxes.exec import CommandResult

VACUOUS = '''
def test_nothing():
    pass


def test_documented():
    """Explains itself and asserts nothing."""


def test_elided():
    ...


async def test_async_nothing():
    pass


def test_real():
    assert 1 + 1 == 2


def helper_pass():
    pass
'''


def test_only_unfailable_test_functions_are_named(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text(VACUOUS)
    found = vacuous_test_names(tmp_path)
    assert found == {"test_nothing", "test_documented", "test_elided", "test_async_nothing"}
    # A test with a real assertion is not vacuous, and a non-test helper whose
    # body is `pass` is none of our business.
    assert "test_real" not in found
    assert "helper_pass" not in found


def test_a_file_that_will_not_parse_is_skipped_not_fatal(tmp_path: Path) -> None:
    """Whether a broken file parses is not a scoring question."""
    (tmp_path / "test_broken.py").write_text("def test_x(:\n")
    (tmp_path / "test_ok.py").write_text("def test_y():\n    pass\n")
    assert vacuous_test_names(tmp_path) == {"test_y"}


def test_class_methods_are_found_too(tmp_path: Path) -> None:
    (tmp_path / "test_cls.py").write_text(
        "class TestThing:\n    def test_inner(self):\n        pass\n"
    )
    assert vacuous_test_names(tmp_path) == {"test_inner"}


def test_case_name_strips_path_class_and_parametrisation() -> None:
    assert _case_name("tests/test_x.py::test_y") == "test_y"
    assert _case_name("tests/test_x.py::TestC::test_y") == "test_y"
    assert _case_name("tests/test_x.py::test_y[case-3]") == "test_y"


# --- end to end through evaluate() ------------------------------------------


def _snapshot(root: Path, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text("VALUE = 1\n")
    (root / "test_suite.py").write_text(body)


PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1 +1 @@\n"
    "-VALUE = 1\n"
    "+VALUE = 2\n"
)


def fake_pytest(*cases: tuple[str, str]):  # type: ignore[no-untyped-def]
    """An executor that reports the given cases in `pytest -v` format."""
    lines = [f"test_suite.py::{name} {outcome}" for name, outcome in cases]

    def execute(command: str, cwd: Path, **kwargs: object) -> CommandResult:
        return CommandResult(
            command=command,
            exit_code=0,
            stdout="\n".join(lines),
            stderr="",
            duration_s=0.1,
        )

    return execute


def test_a_suite_of_only_unfailable_tests_scores_nothing_rather_than_full_marks(
    tmp_path: Path,
) -> None:
    """The headline case. Three `pass` tests all "pass", and before this change
    that was a perfect correctness component for doing nothing at all."""
    source = tmp_path / "base"
    _snapshot(source, "def test_a():\n    pass\n\ndef test_b():\n    pass\n")

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "pytest -v"},
            test_framework="pytest",
        ),
        tmp_path / "work",
        execute=fake_pytest(("test_a", "PASSED"), ("test_b", "PASSED")),
    )

    assert outcome.results["existing_tests"]["excluded_unfailable"] == 2
    assert outcome.results["existing_tests"]["scoreable_cases"] == 0
    # No score part was contributed, so correctness is not 1.0 for a no-op.
    assert outcome.score != 1.0


def test_real_tests_still_score_and_the_unfailable_ones_are_dropped(tmp_path: Path) -> None:
    source = tmp_path / "base"
    _snapshot(
        source,
        "def test_free():\n    pass\n\n"
        "def test_one():\n    assert True\n\n"
        "def test_two():\n    assert True\n",
    )

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "pytest -v"},
            test_framework="pytest",
        ),
        tmp_path / "work",
        execute=fake_pytest(
            ("test_free", "PASSED"), ("test_one", "PASSED"), ("test_two", "FAILED")
        ),
    )

    existing = outcome.results["existing_tests"]
    assert existing["excluded_unfailable"] == 1
    assert existing["scoreable_cases"] == 2
    # 1 of 2 real tests passed — the free pass does not lift it to 2 of 3.
    assert outcome.score == 0.5


def test_pokemon_shaped_suite_reports_no_signal_rather_than_a_wrong_number(
    tmp_path: Path,
) -> None:
    """The exact baseline of Pokemon-Battle-Simulator: three unfailable passes
    and two tests already broken before the agent arrived.

    Counting everything gave 3/5 = 0.6, falsely high. Dropping only the
    unfailable ones gave 0/2 = 0.0, falsely low — inverting the bug, not fixing
    it. With neither kind left there is nothing to score, and saying so is the
    only honest answer available.
    """
    source = tmp_path / "base"
    _snapshot(
        source,
        "def test_type_effectiveness():\n    pass\n\n"
        "def test_damage_calculation():\n    pass\n\n"
        "def test_status_effects():\n    pass\n\n"
        "def test_pokemon_loading():\n    assert False\n\n"
        "def test_basic_functionality():\n    assert False\n",
    )
    baseline = [
        ("test_suite.py::test_type_effectiveness", "passed"),
        ("test_suite.py::test_damage_calculation", "passed"),
        ("test_suite.py::test_status_effects", "passed"),
        ("test_suite.py::test_pokemon_loading", "failed"),
        ("test_suite.py::test_basic_functionality", "failed"),
    ]

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "pytest -v"},
            test_framework="pytest",
            baseline_cases=baseline,
        ),
        tmp_path / "work",
        execute=fake_pytest(
            ("test_type_effectiveness", "PASSED"),
            ("test_damage_calculation", "PASSED"),
            ("test_status_effects", "PASSED"),
            ("test_pokemon_loading", "FAILED"),
            ("test_basic_functionality", "FAILED"),
        ),
    )

    existing = outcome.results["existing_tests"]
    assert existing["excluded_unfailable"] == 3
    assert existing["excluded_pre_existing"] == 2
    assert existing["scoreable_cases"] == 0
    assert outcome.signal == INSUFFICIENT_EVALUATION_SIGNAL
    assert outcome.score is None  # not 0.6, and not 0.0


def test_fixing_a_pre_existing_failure_is_not_punished(tmp_path: Path) -> None:
    """A test broken before the agent arrived is excluded either way — it must
    not drag the score down while it stays broken."""
    source = tmp_path / "base"
    _snapshot(
        source,
        "def test_works():\n    assert True\n\ndef test_was_broken():\n    assert True\n",
    )
    baseline = [
        ("test_suite.py::test_works", "passed"),
        ("test_suite.py::test_was_broken", "failed"),
    ]

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "pytest -v"},
            test_framework="pytest",
            baseline_cases=baseline,
        ),
        tmp_path / "work",
        execute=fake_pytest(("test_works", "PASSED"), ("test_was_broken", "FAILED")),
    )

    existing = outcome.results["existing_tests"]
    assert existing["excluded_pre_existing"] == 1
    assert existing["scoreable_cases"] == 1
    assert outcome.score == 1.0  # the one case it was responsible for still passes


def test_an_unfailable_test_that_breaks_still_counts_as_a_regression(tmp_path: Path) -> None:
    """Excluded from scoring is not excluded from notice: a `pass` test that
    starts failing means the agent broke collection."""
    source = tmp_path / "base"
    _snapshot(source, "def test_free():\n    pass\n\ndef test_one():\n    assert True\n")

    outcome = evaluate(
        EvaluationContext(
            patch=PATCH,
            snapshot_source=source,
            commands={"test": "pytest -v"},
            test_framework="pytest",
            baseline_cases=[
                ("test_suite.py::test_free", "passed"),
                ("test_suite.py::test_one", "passed"),
            ],
        ),
        tmp_path / "work",
        execute=fake_pytest(("test_free", "FAILED"), ("test_one", "PASSED")),
    )

    assert outcome.results["regressions"]["count"] == 1
    assert "test_suite.py::test_free" in outcome.results["regressions"]["cases"]
