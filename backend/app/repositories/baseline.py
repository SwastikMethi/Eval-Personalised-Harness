"""Baseline validation (spec §7): run the configured commands on a clean
snapshot BEFORE any agent touches the repo, storing per-case test identity so
pre-existing failures are never counted as agent regressions (Stage 5).
"""

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluators import runner_repair
from app.evaluators.parsers import PARSERS, parse_generic
from app.sandboxes.exec import CommandResult, Executor, run_host_command


@dataclass
class BaselineOutcome:
    benchmarkable: bool
    warn: bool  # partially failing baseline — proceed with warning
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    test_cases: list[tuple[str, str]] = field(default_factory=list)
    # Changes the REPO needs for its own suite to run — surfaced to the user,
    # never written. A repo whose tests need pytest but whose requirements.txt
    # omits it is a fact about the repo, not a failure of the benchmark.
    suggested_repo_changes: list[dict[str, str]] = field(default_factory=list)
    # True when the suite only ran after the runner was installed for it, so
    # the caller can tell "worked" from "worked once we fixed it".
    repaired: bool = False


# Moved to evaluators/runner_repair.py so the evaluator repairs identically.
# It did not, and a repo whose requirements omit pytest baselined fine and then
# graded every agent at 0.0 — see that module's docstring.
_RUNNER_INSTALL = runner_repair.RUNNER_INSTALL
_looks_like_missing_runner = runner_repair.looks_like_missing_runner


# zsh-style, and unambiguous, so it is tried first: "sh: command not found: poetry".
_MISSING_SUFFIX = re.compile(r"command not found:\s*([\w.+-]+)", re.MULTILINE)
# sh/bash style: "/bin/sh: 1: make: not found", "bash: uv: command not found".
_MISSING_PREFIX = re.compile(r"([\w./+-]+):\s*(?:command\s+)?not found", re.MULTILINE)

# The shell reporting the failure is not the tool that is missing.
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "env"})


def missing_tool(result: CommandResult) -> str | None:
    """The executable a command could not find, if that is why it failed.

    Exit 127 is the shell's "command not found", and the raw Docker build log
    around it is unreadable. Naming the tool turns an opaque wall of build
    output into one actionable sentence.
    """
    text = f"{result.stdout}\n{result.stderr}"

    if match := _MISSING_SUFFIX.search(text):
        return match.group(1)

    for match in _MISSING_PREFIX.finditer(text):
        # `/bin/sh: 1: make` — keep the executable, drop any path prefix.
        name = match.group(1).rsplit("/", 1)[-1]
        if name and name not in _SHELLS:
            return name
    return None


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
            # A failed install used to end the baseline here, which reported
            # "unbenchmarkable" for a repo whose tests may well run — a
            # stdlib-only or vendored project needs no install at all. Say what
            # broke, then let the test step decide whether there is a signal.
            missing = missing_tool(prebuilt_install)
            outcome.steps["install"]["diagnosis"] = (
                f"`{missing}` is not available in the sandbox image, so dependencies "
                f"were not installed. Add it to sandbox-images/python/Dockerfile and "
                f"run `make sandbox-image`, or set an install command that does not "
                f"need it."
                if missing
                else "Installing dependencies failed; continuing without them."
            )
            outcome.warn = True

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

        # The suite did not run because its runner is missing. Install it and
        # try once more, rather than reporting the repo unbenchmarkable.
        # Previously this depended on the analysing model volunteering
        # "&& pip install pytest", so the same repo was scoreable or not
        # depending on model whim.
        if _looks_like_missing_runner(result, test_framework) and (
            install := _RUNNER_INSTALL.get(test_framework or "")
        ):
            outcome.steps["test_before_repair"] = _record(result)
            repair = execute(install, workspace)
            outcome.steps["runner_install"] = _record(repair)
            if repair.exit_code == 0:
                result = execute(test_cmd, workspace)
                report = parser(result)
                outcome.repaired = True
                outcome.suggested_repo_changes.append(
                    {
                        "file": (
                            "requirements.txt" if test_framework == "pytest" else "package.json"
                        ),
                        "add": test_framework or "",
                        "why": (
                            f"the suite needs {test_framework}, but installing the repo's own "
                            f"dependencies does not provide it — every run has to install it first"
                        ),
                    }
                )
        outcome.steps["test"] = _record(result) | {
            "totals": report.totals,
            "parse_ok": report.parse_ok,
            "collection_error": report.collection_error,
        }
        outcome.test_cases = report.cases
        if report.collection_error:
            outcome.benchmarkable = False
            return outcome
        # The command ran and produced NOTHING we can read — a missing runner
        # ("No module named pytest"), a bad invocation, a crash. Reporting that
        # as benchmarkable would let a whole matrix run against a repo whose
        # tests never execute, scoring every agent against silence.
        if result.exit_code != 0 and not report.cases:
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
