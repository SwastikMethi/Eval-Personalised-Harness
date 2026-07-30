"""Test-output parsers with per-case identity (eng review 4A).

Regression comparison (Stage 5) works on stable test-case IDs, never exit
codes — so both baseline and post-agent runs must parse through here.
"""

import re
from dataclasses import dataclass, field

from app.sandboxes.exec import CommandResult

Outcome = str  # passed | failed | skipped | xfail | error

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _clean(text: str) -> str:
    """Strip ANSI color codes — test runners colorize even captured output."""
    return _ANSI.sub("", text)


@dataclass
class TestReport:
    cases: list[tuple[str, Outcome]] = field(default_factory=list)
    parse_ok: bool = True
    collection_error: bool = False

    @property
    def totals(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, outcome in self.cases:
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    @property
    def passed(self) -> int:
        return self.totals.get("passed", 0)

    @property
    def failed(self) -> int:
        return self.totals.get("failed", 0) + self.totals.get("error", 0)


_PYTEST_LINE = re.compile(
    r"^(?P<id>\S+::\S+)\s+(?P<outcome>PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)", re.M
)
_PYTEST_OUTCOMES = {
    "PASSED": "passed",
    "FAILED": "failed",
    "SKIPPED": "skipped",
    "XFAIL": "xfail",
    "XPASS": "passed",
    "ERROR": "error",
}


def parse_pytest(result: CommandResult) -> TestReport:
    """Parse `pytest -v` output into per-case results."""
    out = _clean(result.stdout + "\n" + result.stderr)
    if "error" in out.lower() and ("collected 0 items" in out or "errors during collection" in out):
        return TestReport(parse_ok=False, collection_error=True)
    cases = [
        (m.group("id"), _PYTEST_OUTCOMES[m.group("outcome")]) for m in _PYTEST_LINE.finditer(out)
    ]
    if not cases and result.exit_code != 0:
        return TestReport(parse_ok=False)
    return TestReport(cases=cases)


_VITEST_LINE = re.compile(r"^\s*(?P<mark>✓|✗|×|↓|✘)\s+(?P<id>.+?)(?:\s+\d+\s*ms)?\s*$", re.M)
_VITEST_MARKS = {"✓": "passed", "✗": "failed", "×": "failed", "✘": "failed", "↓": "skipped"}


def parse_vitest(result: CommandResult) -> TestReport:
    """Parse vitest/jest verbose reporter output into per-case results."""
    out = _clean(result.stdout + "\n" + result.stderr)
    cases = [
        (m.group("id").strip(), _VITEST_MARKS[m.group("mark")])
        for m in _VITEST_LINE.finditer(out)
    ]
    if not cases and result.exit_code != 0:
        return TestReport(parse_ok=False)
    return TestReport(cases=cases)


def parse_generic(result: CommandResult) -> TestReport:
    """Exit-code-only fallback: no case identity, parse_ok=False by design."""
    outcome: Outcome = "passed" if result.exit_code == 0 else "failed"
    return TestReport(cases=[("__command__", outcome)], parse_ok=False)


PARSERS = {"pytest": parse_pytest, "vitest": parse_vitest, "generic": parse_generic}
