"""Installing a test runner the repo forgot to declare.

Shared by the baseline and the evaluator, and it has to be shared or the two
measure different machines. `Pokemon-Battle-Simulator` lists mcp, pandas,
requests and pydantic in `requirements.txt` and never mentions pytest. The
baseline noticed, installed it, and reported five test cases. Grading did not,
so `python -m pytest -v` died in 55 ms with nothing to parse, all three
baseline-passing tests looked like they had vanished, and every agent scored
0.0 no matter what it wrote.

That is the same failure as Known Defect #16 wearing different clothes: the
tree the baseline measures and the tree the patch is graded in must be the same
tree, right down to what is installed in it.

Deliberately not a dependency solver. These are test runners — the thing
without which a suite cannot execute at all.
"""

from app.sandboxes.exec import CommandResult

# A runner that is not installed produces one of these, and the message is the
# only reliable signal: exit codes vary (1 from python -m, 127 from a shell).
MISSING_RUNNER_PATTERNS = (
    "no module named",
    "not found",
    "command not found",
    "is not recognized",
)

RUNNER_INSTALL = {
    "pytest": "python -m pip install pytest",
    "vitest": "npm install --no-save vitest",
    "jest": "npm install --no-save jest",
}


def looks_like_missing_runner(result: CommandResult, runner: str | None) -> bool:
    """Did the test command fail because its runner is absent?

    Distinct from "the tests failed": a suite that runs and reports failures is
    a legitimate result, while a runner that was never installed means the
    suite did not execute at all.
    """
    if result.exit_code == 0 or not runner:
        return False
    haystack = f"{result.stdout}\n{result.stderr}".lower()
    return runner.lower() in haystack and any(p in haystack for p in MISSING_RUNNER_PATTERNS)


def install_command(runner: str | None) -> str | None:
    return RUNNER_INSTALL.get(runner or "")
