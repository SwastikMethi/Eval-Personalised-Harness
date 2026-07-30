from app.evaluators.parsers import parse_generic, parse_pytest, parse_vitest
from app.sandboxes.exec import CommandResult


def cmd(stdout: str, exit_code: int = 0) -> CommandResult:
    return CommandResult(
        command="x", exit_code=exit_code, stdout=stdout, stderr="", duration_s=0.1
    )


PYTEST_OUT = """
tests/test_a.py::test_one PASSED
tests/test_a.py::test_two FAILED
tests/test_b.py::test_skip SKIPPED
tests/test_b.py::test_xf XFAIL
tests/test_b.py::test_err ERROR
"""


def test_pytest_case_identity() -> None:
    report = parse_pytest(cmd(PYTEST_OUT, exit_code=1))
    assert ("tests/test_a.py::test_one", "passed") in report.cases
    assert ("tests/test_a.py::test_two", "failed") in report.cases
    assert report.totals == {"passed": 1, "failed": 1, "skipped": 1, "xfail": 1, "error": 1}
    assert report.failed == 2  # failed + error
    assert report.parse_ok


def test_pytest_collection_error() -> None:
    out = "ERROR tests/test_x.py\ncollected 0 items / 1 error\n2 errors during collection"
    report = parse_pytest(cmd(out, exit_code=2))
    assert report.collection_error
    assert not report.parse_ok


def test_pytest_unparseable_failure_not_zero_tests() -> None:
    report = parse_pytest(cmd("segfault", exit_code=139))
    assert not report.parse_ok
    assert report.cases == []


VITEST_OUT = """
 ✓ src/a.test.ts > adds numbers 3ms
 ✗ src/a.test.ts > subtracts numbers 1ms
 ↓ src/b.test.ts > skipped case
"""


def test_vitest_case_identity() -> None:
    report = parse_vitest(cmd(VITEST_OUT, exit_code=1))
    assert len(report.cases) == 3
    assert report.passed == 1
    assert report.failed == 1
    assert report.totals.get("skipped") == 1


def test_generic_fallback_flags_no_identity() -> None:
    report = parse_generic(cmd("done", exit_code=0))
    assert not report.parse_ok
    assert report.passed == 1
    report_fail = parse_generic(cmd("boom", exit_code=1))
    assert report_fail.failed == 1
