"""Baseline validation (spec §7): run the configured commands on a clean
snapshot BEFORE any agent touches the repo, storing per-case test identity so
pre-existing failures are never counted as agent regressions (Stage 5).
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluators.parsers import PARSERS, parse_generic
from app.sandboxes.exec import CommandResult, Executor, run_host_command


@dataclass
class BaselineOutcome:
    benchmarkable: bool
    warn: bool  # partially failing baseline — proceed with warning
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    test_cases: list[tuple[str, str]] = field(default_factory=list)


def _record(result: CommandResult) -> dict[str, Any]:
    data = asdict(result)
    data["stdout"] = data["stdout"][-20000:]
    data["stderr"] = data["stderr"][-20000:]
    return data


def run_baseline(
    workspace: Path,
    commands: dict[str, str | None],
    test_framework: str | None,
    execute: Executor = run_host_command,
    prebuilt_install: CommandResult | None = None,
) -> BaselineOutcome:
    """`execute` runs each command. Production passes a container-backed
    executor so install and test share one interpreter; unit tests keep the
    host default and stay fast.

    `prebuilt_install` is the result of installing dependencies at image build
    time — recorded as the install step so the user sees it, without paying for
    the install twice.
    """
    outcome = BaselineOutcome(benchmarkable=True, warn=False)

    if prebuilt_install is not None:
        outcome.steps["install"] = _record(prebuilt_install)
        if prebuilt_install.exit_code != 0:
            outcome.benchmarkable = False
            return outcome

    for step in ("install", "build"):
        cmd = commands.get(step)
        if not cmd or (step == "install" and prebuilt_install is not None):
            continue
        result = execute(cmd, workspace)
        outcome.steps[step] = _record(result)
        if result.exit_code != 0:
            outcome.benchmarkable = False
            return outcome

    test_cmd = commands.get("test")
    if test_cmd:
        result = execute(test_cmd, workspace)
        parser = PARSERS.get(test_framework or "generic", parse_generic)
        report = parser(result)
        outcome.steps["test"] = _record(result) | {
            "totals": report.totals,
            "parse_ok": report.parse_ok,
            "collection_error": report.collection_error,
        }
        outcome.test_cases = report.cases
        if report.collection_error:
            outcome.benchmarkable = False
            return outcome
        if report.failed:
            outcome.warn = True  # spec §7: warn-and-proceed on partial failure

    for step in ("lint", "typecheck"):
        cmd = commands.get(step)
        if not cmd:
            continue
        result = execute(cmd, workspace)
        outcome.steps[step] = _record(result)
        if result.exit_code != 0:
            outcome.warn = True

    return outcome
