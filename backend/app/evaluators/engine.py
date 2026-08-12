"""Evaluation engine (spec §15, eng review Tension 2).

Grading never happens in the agent's workspace: the ONLY agent input is the
patch, applied to a fresh snapshot with evaluator-owned commands. A tampering
agent (deleted tests, edited configs) is caught by ProhibitedFilesEvaluator
and by the fact that the graded tree never saw its non-patch side effects.

ponytail: MVP executes evaluator commands on the host against the fresh
snapshot (same trust level as Stage-2 baseline); moving execution into a
fresh container is the Stage-7 hardening step.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.evaluators.parsers import PARSERS, TestReport, parse_generic
from app.sandboxes.exec import Executor, run_host_command

PROHIBITED_PATTERNS = (
    r"(^|/)tests?/",
    r"(^|/)__tests__/",
    r"(^|/)spec/",
    r".*\.test\.[jt]sx?$",
    r".*\.spec\.[jt]sx?$",
    r"(^|/)test_[^/]+\.py$",
    r"(^|/)[^/]+_test\.py$",
    r"(^|/)conftest\.py$",
    r"(^|/)pytest\.ini$",
    r"(^|/)\.github/",
    r"(^|/)Makefile$",
)

INSUFFICIENT_EVALUATION_SIGNAL = "INSUFFICIENT_EVALUATION_SIGNAL"


@dataclass
class EvaluationContext:
    patch: str | None
    snapshot_source: Path  # pristine base tree to copy for grading
    commands: dict[str, str | None]  # evaluator-owned, never from the patch
    test_framework: str | None
    baseline_cases: list[tuple[str, str]] = field(default_factory=list)
    hidden_tests: dict[str, str] = field(default_factory=dict)  # relpath -> content


@dataclass
class EvaluationOutcome:
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    signal: str = "ok"  # ok | INSUFFICIENT_EVALUATION_SIGNAL
    score: float | None = None  # normalized 0..1 correctness signal


def patch_touched_files(patch: str) -> list[str]:
    files = []
    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path != "/dev/null":
                files.append(path)
    return files


def prohibited_files(patch: str) -> list[str]:
    return [
        f
        for f in patch_touched_files(patch)
        if any(re.search(p, f) for p in PROHIBITED_PATTERNS)
    ]


def _apply_patch(workspace: Path, patch: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=workspace,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0, proc.stderr[:1000]


def _patch_stats(patch: str) -> dict[str, int]:
    added = sum(
        1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")
    )
    return {
        "files": len(patch_touched_files(patch)),
        "lines_added": added,
        "lines_removed": removed,
    }


def _run_tests(
    workspace: Path,
    command: str,
    framework: str | None,
    execute: Executor = run_host_command,
) -> tuple[TestReport, dict[str, Any]]:
    result = execute(command, workspace)
    parser = PARSERS.get(framework or "generic", parse_generic)
    report = parser(result)
    return report, {
        "exit_code": result.exit_code,
        "totals": report.totals,
        "parse_ok": report.parse_ok,
        "duration_s": result.duration_s,
    }


def _regressions(
    baseline: list[tuple[str, str]], post: list[tuple[str, str]]
) -> list[str]:
    """Identity-based: cases that PASSED at baseline and fail (or vanished) now.

    Vanished tests count as regressions — an agent that deletes tests from the
    codebase (undetected by the prohibited gate on renamed paths) must not
    profit. Flaky/changed inventory shows up here explicitly, not silently.
    """
    baseline_passed = {case for case, outcome in baseline if outcome == "passed"}
    post_outcomes = dict(post)
    return sorted(
        case
        for case in baseline_passed
        if post_outcomes.get(case, "missing") not in ("passed", "skipped", "xfail")
    )


def evaluate(
    context: EvaluationContext, workdir: Path, execute: Executor = run_host_command
) -> EvaluationOutcome:
    """Grade a patch. `workdir` is a scratch dir owned by the caller."""
    import shutil

    outcome = EvaluationOutcome()

    if not context.patch or not context.patch.strip():
        outcome.results["patch"] = {"produced": False}
        outcome.score = 0.0
        return outcome
    outcome.results["patch"] = {"produced": True, **_patch_stats(context.patch)}

    bad = prohibited_files(context.patch)
    outcome.results["prohibited_files"] = {"violations": bad}
    if bad:
        outcome.score = 0.0
        return outcome

    workspace = workdir / "graded"
    shutil.copytree(context.snapshot_source, workspace)
    applied, apply_error = _apply_patch(workspace, context.patch)
    outcome.results["apply"] = {"ok": applied, "error": apply_error if not applied else None}
    if not applied:
        outcome.score = 0.0
        return outcome

    has_signal = False
    score_parts: list[float] = []

    if build_cmd := context.commands.get("build"):
        result = execute(build_cmd, workspace)
        ok = result.exit_code == 0
        outcome.results["build"] = {"ok": ok, "exit_code": result.exit_code}
        has_signal = True
        score_parts.append(1.0 if ok else 0.0)
        if not ok:
            outcome.score = 0.0
            return outcome

    if test_cmd := context.commands.get("test"):
        report, meta = _run_tests(workspace, test_cmd, context.test_framework, execute)
        outcome.results["existing_tests"] = meta
        has_signal = has_signal or report.parse_ok or bool(report.cases)
        regressions = _regressions(context.baseline_cases, report.cases)
        outcome.results["regressions"] = {"count": len(regressions), "cases": regressions[:50]}
        total = max(len(report.cases), 1)
        score_parts.append(report.passed / total if report.cases else 0.0)
        if regressions:
            score_parts.append(0.0)

    if context.hidden_tests:
        for relpath, content in context.hidden_tests.items():
            target = workspace / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        hidden_cmd = context.commands.get("test") or "pytest -v"
        report, meta = _run_tests(workspace, hidden_cmd, context.test_framework, execute)
        outcome.results["hidden_tests"] = meta
        has_signal = True
        total = max(len(report.cases), 1)
        score_parts.append(report.passed / total if report.cases else 0.0)

    for step in ("lint", "typecheck"):
        if cmd := context.commands.get(step):
            result = execute(cmd, workspace)
            outcome.results[step] = {"ok": result.exit_code == 0}

    if not has_signal:
        outcome.signal = INSUFFICIENT_EVALUATION_SIGNAL
        outcome.score = None
        return outcome

    outcome.score = sum(score_parts) / len(score_parts) if score_parts else None
    return outcome
