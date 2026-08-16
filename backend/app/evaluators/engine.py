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

from app.evaluators import runner_repair
from app.evaluators.parsers import PARSERS, TestReport, parse_generic
from app.repositories.detectors import vacuous_test_names
from app.sandboxes.exec import Executor, run_host_command


def _case_name(case_id: str) -> str:
    """`tests/test_x.py::TestC::test_y` -> `test_y`."""
    return case_id.rsplit("::", 1)[-1].split("[", 1)[0]

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

    # The baseline installs a missing test runner; grading must do the same or
    # the two measure different machines. Without this, a repo whose
    # requirements omit pytest baselines at five cases and then grades every
    # agent at 0.0 — measured, not hypothetical.
    runner_installed = False
    if runner_repair.looks_like_missing_runner(result, framework) and (
        install := runner_repair.install_command(framework)
    ):
        if execute(install, workspace).exit_code == 0:
            result = execute(command, workspace)
            report = parser(result)
            runner_installed = True

    return report, {
        "exit_code": result.exit_code,
        "totals": report.totals,
        "parse_ok": report.parse_ok,
        "duration_s": result.duration_s,
        "runner_installed": runner_installed,
        # exit_code alone is undiagnosable. The baseline learned this ("exit 2
        # is undiagnosable without opening the database by hand") and the
        # evaluator did not, so a 55ms failure needed a manual docker run to
        # explain. Only kept when there is nothing better to look at.
        "output": (result.stdout + result.stderr)[-4000:] if not report.cases else "",
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
        # A suite that collected nothing and produced unreadable output did not
        # run; it is not "every test regressed at once". Treating it as the
        # latter produced three phantom regressions on a repo missing pytest,
        # which supplied a 0.0 score AND made `has_signal` true — so the run
        # looked measured, stayed eligible, and a winner was declared from a
        # 0.0 vs 0.0 tie. That breaks "do not produce a winner from weak
        # evaluation signal" (CLAUDE.md §4).
        suite_failed = not report.cases and not report.parse_ok
        outcome.results["existing_tests"] = meta | {"suite_failed": suite_failed}

        # Regressions are counted over EVERY case that DID run, unfailable ones
        # included: a test that could not fail and now does means the agent
        # broke collection, which is exactly the damage this check exists to catch.
        regressions = [] if suite_failed else _regressions(context.baseline_cases, report.cases)
        outcome.results["regressions"] = {
            "count": len(regressions),
            "cases": regressions[:50],
            "not_computed": suite_failed,
        }

        # Scoring is a different question from regression, and two kinds of case
        # answer it with no information at all:
        #
        #   unfailable  — body is `pass`, so it succeeds for a correct patch and
        #                 an empty one alike and rewards every agent equally.
        #   pre-existing — already failing before the agent touched anything, so
        #                 counting it punishes every agent equally.
        #
        # Dropping only the first inverts the bug rather than fixing it: on a
        # suite of three `pass` tests and two broken ones the score went from a
        # falsely high 3/5 to a falsely low 0/2. Both are wrong; with neither
        # kind left there is simply no signal, which is a valid answer here.
        vacuous = vacuous_test_names(workspace)
        already_failing = {
            case for case, res in context.baseline_cases if res not in ("passed", "skipped")
        }
        scoreable = [
            (cid, res)
            for cid, res in report.cases
            if _case_name(cid) not in vacuous and cid not in already_failing
        ]
        outcome.results["existing_tests"] = meta | {
            "suite_failed": suite_failed,
            "excluded_unfailable": sum(
                1 for cid, _ in report.cases if _case_name(cid) in vacuous
            ),
            "excluded_pre_existing": sum(
                1 for cid, _ in report.cases if cid in already_failing
            ),
            "scoreable_cases": len(scoreable),
        }
        # "Signal" is whether anything here could distinguish one agent from
        # another, which `parse_ok` never answered — output we could READ is not
        # the same as output that means something. A suite of only unfailable and
        # already-broken cases is unreadable in that sense however cleanly it
        # parses; a regression is signal even when nothing is scoreable.
        has_signal = has_signal or bool(scoreable) or bool(regressions)

        if scoreable:
            passed = sum(1 for _, res in scoreable if res == "passed")
            score_parts.append(passed / len(scoreable))
        # else: the suite carries no information, so it gets no vote rather than
        # a zero — hidden tests then decide correctness on their own, and if
        # there are none the run reports INSUFFICIENT_EVALUATION_SIGNAL.
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
