"""Baseline validation (spec §7): run the configured commands on a clean
snapshot BEFORE any agent touches the repo, storing per-case test identity so
pre-existing failures are never counted as agent regressions (Stage 5).
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluators.parsers import PARSERS, parse_generic
from app.sandboxes.exec import CommandResult, run_host_command


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
) -> BaselineOutcome:
    outcome = BaselineOutcome(benchmarkable=True, warn=False)

    for step in ("install", "build"):
        cmd = commands.get(step)
        if not cmd:
            continue
        result = run_host_command(cmd, workspace)
        outcome.steps[step] = _record(result)
        if result.exit_code != 0:
            outcome.benchmarkable = False
            return outcome

    test_cmd = commands.get("test")
    if test_cmd:
        result = run_host_command(test_cmd, workspace)
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
        result = run_host_command(cmd, workspace)
        outcome.steps[step] = _record(result)
        if result.exit_code != 0:
            outcome.warn = True

    return outcome
