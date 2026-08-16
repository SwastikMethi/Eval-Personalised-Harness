"""Generated hidden tests, and the gate that decides whether to trust one.

The property under test throughout: a generated test earns its place ONLY by
failing on the unfixed code and passing on the fixed code. Everything else here
exists to make that check honest — the filename is ours so its cases can be
identified, a candidate missing at the parent is rejected rather than assumed
broken-in-our-favour, and a rejection always carries its reason.

Docker is not involved: the baseline runner is injected, so the gate's logic is
tested against scripted outcomes rather than against a container's mood.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.tasks.generate_tests import (
    GenerationError,
    extract_test_source,
    generate_verified_test,
    generated_relpath,
    verify_generated_test,
)
from tests.test_repo_service import make_git_repo


def two_commit_repo(root: Path) -> tuple[str, str]:
    """A repo with a parent and a fix commit. Returns (parent_sha, target_sha)."""
    make_git_repo(root, {"src/calc.py": "def add(a, b):\n    return a - b\n"})
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "fix add"],
        cwd=root,
        check=True,
    )
    target = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    return parent, target


def scripted(*rounds: list[tuple[str, str]]) -> Any:
    """A baseline runner that reports each round's cases in order."""
    remaining = list(rounds)

    def run(
        workspace: Path, commands: dict[str, str | None], framework: str | None, repo_id: str
    ) -> Any:
        return SimpleNamespace(test_cases=remaining.pop(0))

    return run


CASE = "tests/test_aso_generated_{sha}.py::test_add_is_addition"
SOURCE = "def test_add_is_addition():\n    from src.calc import add\n    assert add(2, 2) == 4\n"


# --- extraction -------------------------------------------------------------


def test_fenced_block_is_extracted() -> None:
    text = "Here you go:\n```python\ndef test_x():\n    assert True\n```\nHope that helps."
    assert extract_test_source(text) == "def test_x():\n    assert True\n"


def test_unfenced_reply_still_works() -> None:
    """Models drop the fence often enough that refusing would waste an attempt."""
    assert "def test_x" in extract_test_source("def test_x():\n    assert True")


def test_a_commit_with_no_behaviour_to_test_is_not_a_failure() -> None:
    with pytest.raises(GenerationError, match="no behavioural change"):
        extract_test_source("NO_BEHAVIOURAL_CHANGE")


def test_prose_without_a_test_function_is_rejected() -> None:
    with pytest.raises(GenerationError, match="no test function"):
        extract_test_source("```python\nx = 1\n```")


# --- naming -----------------------------------------------------------------


def test_generated_file_lands_beside_existing_tests_with_our_own_name() -> None:
    """The name is ours, not the model's: pytest ids are `path::name`, so a
    unique stem is what lets the gate tell this file's cases from the suite's —
    and a model-chosen path could overwrite a real test."""
    assert generated_relpath("3e4e48def", "tests/unit/test_thing.py") == (
        "tests/unit/test_aso_generated_3e4e48d.py"
    )
    assert generated_relpath("abc1234def", None) == "tests/test_aso_generated_abc1234.py"


# --- the gate ---------------------------------------------------------------


def test_fail_at_parent_then_pass_at_solution_is_accepted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, "tests/test_x.py")
    case = f"{relpath}::test_add_is_addition"

    ok, reason, evidence = verify_generated_test(
        repo,
        parent,
        target,
        relpath,
        SOURCE,
        {"test": "pytest -v"},
        "pytest",
        "repo-1",
        run_baseline=scripted([(case, "failed")], [(case, "passed")]),
    )
    assert ok, reason
    assert evidence["at_parent"] == [(case, "failed")]
    assert evidence["at_solution"] == [(case, "passed")]


def test_a_test_that_already_passes_on_broken_code_is_rejected(tmp_path: Path) -> None:
    """This is the exact failure mode the whole feature exists to prevent: a
    test that cannot fail grades every patch identically."""
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, None)
    case = f"{relpath}::test_add_is_addition"

    ok, reason, _ = verify_generated_test(
        repo, parent, target, relpath, SOURCE, {"test": "pytest -v"}, "pytest", "r",
        run_baseline=scripted([(case, "passed")]),
    )
    assert not ok
    assert "cannot detect the bug" in reason


def test_a_test_missing_at_the_parent_is_rejected_not_assumed_failed(tmp_path: Path) -> None:
    """Absence usually means a module-level import of something that only
    exists after the fix. That breaks collection for the whole suite, so
    reading it as "it failed, good" would corrupt the graded run."""
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, None)

    ok, reason, _ = verify_generated_test(
        repo, parent, target, relpath, SOURCE, {"test": "pytest -v"}, "pytest", "r",
        run_baseline=scripted([("tests/test_other.py::test_unrelated", "passed")]),
    )
    assert not ok
    assert "fails to import" in reason


def test_a_test_that_fails_on_the_fixed_code_too_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, None)
    case = f"{relpath}::test_add_is_addition"

    ok, reason, _ = verify_generated_test(
        repo, parent, target, relpath, SOURCE, {"test": "pytest -v"}, "pytest", "r",
        run_baseline=scripted([(case, "failed")], [(case, "failed")]),
    )
    assert not ok
    assert "wrong" in reason


# --- retry loop -------------------------------------------------------------


class ScriptedModel:
    """Returns each reply in turn and records the rejection nudges it saw."""

    name = "stub"

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.nudges: list[str] = []

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> Any:
        last = str(messages[-1].get("content", ""))
        if "previous attempt was rejected" in last:
            self.nudges.append(last)
        return SimpleNamespace(content=self._replies.pop(0))


async def test_a_rejected_candidate_is_retried_with_the_reason(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, None)
    case = f"{relpath}::test_add_is_addition"

    model = ScriptedModel(f"```python\n{SOURCE}```", f"```python\n{SOURCE}```")
    result = await generate_verified_test(
        model,  # type: ignore[arg-type]
        "m1",
        repo,
        parent,
        target,
        "fix add",
        {"test": "pytest -v"},
        "pytest",
        "r",
        run_baseline=scripted(
            [(case, "passed")],  # attempt 1: useless test, rejected
            [(case, "failed")],  # attempt 2: fails at parent...
            [(case, "passed")],  # ...and passes at solution
        ),
    )

    assert result.verified
    assert result.attempts == 2
    assert result.reject_reason is None
    assert len(model.nudges) == 1
    assert "cannot detect the bug" in model.nudges[0]


async def test_giving_up_still_reports_why(tmp_path: Path) -> None:
    """A silent "no tests generated" is how you end up back at a fake score."""
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, None)
    case = f"{relpath}::test_add_is_addition"

    model = ScriptedModel(*[f"```python\n{SOURCE}```"] * 3)
    result = await generate_verified_test(
        model,  # type: ignore[arg-type]
        "m1", repo, parent, target, "fix add", {"test": "pytest -v"}, "pytest", "r",
        run_baseline=scripted(*[[(case, "passed")]] * 3),
    )

    assert not result.verified
    assert result.attempts == 3
    assert result.reject_reason and "cannot detect the bug" in result.reject_reason


async def test_an_empty_reply_is_retried_not_treated_as_a_verdict(tmp_path: Path) -> None:
    """Measured against gpt-5.6-sol: the first attempt came back empty because
    reasoning consumed the token budget. Giving up there threw away a perfectly
    testable commit, which is the opposite of what a retry budget is for."""
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)
    relpath = generated_relpath(target, None)
    case = f"{relpath}::test_add_is_addition"

    model = ScriptedModel("", f"```python\n{SOURCE}```")
    result = await generate_verified_test(
        model,  # type: ignore[arg-type]
        "m1", repo, parent, target, "fix add", {"test": "pytest -v"}, "pytest", "r",
        run_baseline=scripted([(case, "failed")], [(case, "passed")]),
    )

    assert result.verified
    assert result.attempts == 2
    assert "empty test file" in model.nudges[0]


async def test_a_docs_only_commit_is_not_retried(tmp_path: Path) -> None:
    """Three calls for a commit with nothing to test is three wasted calls."""
    repo = tmp_path / "repo"
    parent, target = two_commit_repo(repo)

    model = ScriptedModel("NO_BEHAVIOURAL_CHANGE")
    result = await generate_verified_test(
        model,  # type: ignore[arg-type]
        "m1", repo, parent, target, "docs", {"test": "pytest -v"}, "pytest", "r",
        run_baseline=scripted(),
    )

    assert not result.verified
    assert result.attempts == 1
    assert result.reject_reason and "no behavioural change" in result.reject_reason
