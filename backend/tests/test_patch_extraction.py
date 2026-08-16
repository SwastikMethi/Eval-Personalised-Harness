"""What a harness hands back must be appliable, and must be the agent's work.

Paid for by a live run: mini-swe-agent wrote a correct two-file fix to
`Pokemon-Battle-Simulator` and scored **0.0**. Running the code had regenerated
eight `.pyc` files, `git add -A` swept them in, and `git apply` rejected the
whole patch — "cannot apply binary patch to 'src/__pycache__/…pyc' without full
index line". The agent's real change was never graded and the generated hidden
test never ran.

Two properties, both load-bearing:
  1. compiled Python never reaches the patch — it is derived from the .py files
     in the same diff, so grading it is meaningless even when it applies;
  2. what does reach the patch applies cleanly to a fresh checkout.
"""

import subprocess
from pathlib import Path

from app.harnesses.base import PATCH_EXTRACT_COMMAND


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def _repo_that_commits_pyc(root: Path) -> None:
    """Mirrors the real repo: __pycache__ is tracked, not ignored."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "src" / "__pycache__").mkdir(parents=True)
    (root / "src" / "app.py").write_text("VALUE = 1\n")
    (root / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00\x01stale")
    _git(["init", "-q", "-b", "main"], root)
    _git(["add", "-A"], root)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root,
        check=True,
    )


def _agent_edits_and_runs(root: Path) -> None:
    """A source edit plus the .pyc churn that executing the code produces."""
    (root / "src" / "app.py").write_text("VALUE = 2\n")
    (root / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00\x02fresh")


def extract(root: Path) -> str:
    return subprocess.run(
        PATCH_EXTRACT_COMMAND, cwd=root, shell=True, capture_output=True, text=True
    ).stdout


def test_compiled_python_never_reaches_the_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo_that_commits_pyc(repo)
    _agent_edits_and_runs(repo)

    patch = extract(repo)
    assert "src/app.py" in patch
    assert "__pycache__" not in patch
    assert ".pyc" not in patch


def test_the_extracted_patch_applies_to_a_fresh_checkout(tmp_path: Path) -> None:
    """The regression itself: the old command emitted an unappliable
    `Binary files … differ` for the .pyc and `git apply` refused the lot."""
    repo = tmp_path / "repo"
    _repo_that_commits_pyc(repo)
    _agent_edits_and_runs(repo)
    patch = extract(repo)

    graded = tmp_path / "graded"
    _repo_that_commits_pyc(graded)
    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=graded,
        input=patch,
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    assert (graded / "src" / "app.py").read_text() == "VALUE = 2\n"


def test_the_old_command_really_did_fail_this_way(tmp_path: Path) -> None:
    """Guards the reasoning, not just the fix: if plain `git diff --cached`
    ever stops producing an unappliable diff here, the exclusions could be
    reconsidered. Until then this documents why they exist."""
    repo = tmp_path / "repo"
    _repo_that_commits_pyc(repo)
    _agent_edits_and_runs(repo)
    _git(["add", "-A"], repo)
    old = subprocess.run(
        "git diff --cached", cwd=repo, shell=True, capture_output=True, text=True
    ).stdout

    graded = tmp_path / "graded"
    _repo_that_commits_pyc(graded)
    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=graded,
        input=old,
        capture_output=True,
        text=True,
    )
    assert applied.returncode != 0
    assert "binary" in applied.stderr.lower()


def test_a_legitimate_binary_asset_still_survives(tmp_path: Path) -> None:
    """`--binary` is not incidental: an agent that adds a real binary fixture
    must still be gradeable. Only compiled Python is excluded."""
    repo = tmp_path / "repo"
    _repo_that_commits_pyc(repo)
    (repo / "fixture.bin").write_bytes(b"\x00\x01\x02real asset")

    patch = extract(repo)
    assert "fixture.bin" in patch

    graded = tmp_path / "graded"
    _repo_that_commits_pyc(graded)
    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=graded,
        input=patch,
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    assert (graded / "fixture.bin").read_bytes() == b"\x00\x01\x02real asset"
