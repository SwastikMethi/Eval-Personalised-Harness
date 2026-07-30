from pathlib import Path

from app.evaluators.engine import (
    INSUFFICIENT_EVALUATION_SIGNAL,
    EvaluationContext,
    evaluate,
    prohibited_files,
)

GOOD_PATCH = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def greet():
-    return "helo"
+    return "hello"
"""

TEST_TAMPER_PATCH = """--- a/test_app.py
+++ b/test_app.py
@@ -1,2 +1,2 @@
-def test_greet(): assert greet() == "hello"
+def test_greet(): assert True
"""


def make_snapshot(root: Path) -> Path:
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text('def greet():\n    return "helo"\n')
    (src / "test_app.py").write_text(
        "from app import greet\n\ndef test_greet():\n    assert greet() == 'hello'\n"
    )
    return src


def ctx(snapshot: Path, patch: str | None, **kwargs: object) -> EvaluationContext:
    defaults: dict = {
        "commands": {"test": "python -m pytest -v"},
        "test_framework": "pytest",
    }
    defaults.update(kwargs)
    return EvaluationContext(patch=patch, snapshot_source=snapshot, **defaults)  # type: ignore[arg-type]


def test_good_patch_scores_high(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    outcome = evaluate(ctx(snapshot, GOOD_PATCH), tmp_path / "w1")
    assert outcome.results["apply"]["ok"]
    assert outcome.score == 1.0


def test_empty_patch_scores_zero(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    outcome = evaluate(ctx(snapshot, None), tmp_path / "w2")
    assert outcome.results["patch"] == {"produced": False}
    assert outcome.score == 0.0


def test_test_tampering_rejected(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    outcome = evaluate(ctx(snapshot, TEST_TAMPER_PATCH), tmp_path / "w3")
    assert outcome.results["prohibited_files"]["violations"] == ["test_app.py"]
    assert outcome.score == 0.0


def test_unapplicable_patch_is_agent_failure(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    bad = GOOD_PATCH.replace('return "helo"', 'return "nonexistent context"')
    outcome = evaluate(ctx(snapshot, bad), tmp_path / "w4")
    assert not outcome.results["apply"]["ok"]
    assert outcome.score == 0.0


def test_regression_detected_by_identity(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    breaking = GOOD_PATCH.replace('+    return "hello"', '+    raise RuntimeError("broken")')
    baseline = [("test_app.py::test_greet", "passed")]
    outcome = evaluate(
        ctx(snapshot, breaking, baseline_cases=baseline), tmp_path / "w5"
    )
    assert outcome.results["regressions"]["count"] == 1
    assert outcome.score is not None and outcome.score < 0.5


def test_vanished_baseline_test_counts_as_regression(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    baseline = [("test_app.py::test_gone", "passed")]
    outcome = evaluate(ctx(snapshot, GOOD_PATCH, baseline_cases=baseline), tmp_path / "w6")
    assert "test_app.py::test_gone" in outcome.results["regressions"]["cases"]


def test_hidden_tests_run_after_patch(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    hidden = {
        "test_hidden.py": "from app import greet\n\ndef test_hidden():\n"
        "    assert greet().startswith('h')\n"
    }
    outcome = evaluate(ctx(snapshot, GOOD_PATCH, hidden_tests=hidden), tmp_path / "w7")
    assert outcome.results["hidden_tests"]["totals"].get("passed", 0) >= 1


def test_insufficient_signal_when_no_evaluators(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    outcome = evaluate(
        ctx(snapshot, GOOD_PATCH, commands={}), tmp_path / "w8"
    )
    assert outcome.signal == INSUFFICIENT_EVALUATION_SIGNAL
    assert outcome.score is None


def test_prohibited_patterns() -> None:
    patch = "--- a/x\n+++ b/.github/workflows/ci.yml\n+++ b/src/main.py\n"
    assert prohibited_files(patch) == [".github/workflows/ci.yml"]
