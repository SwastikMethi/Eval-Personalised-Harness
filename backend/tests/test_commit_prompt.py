"""Commit-replay prompts must ask for work, not report it.

The first real matrix produced zero patches because the prompt was the raw
commit message. Given "added tool to get pokemon data and added logger file",
the agent replied "Acknowledged: ... have been added. Please provide a specific
task" and stopped. Past-tense prose describing finished work is a status
report, not an instruction.

The opposite failure is just as bad: putting the diff in the prompt would hand
over the answer and reduce the benchmark to transcription.
"""

import subprocess
from pathlib import Path

from app.tasks.historical import commit_task_description
from tests.test_repo_service import make_git_repo


def _repo_with_change(root: Path) -> str:
    make_git_repo(root, {"app.py": "def median(xs):\n    return sorted(xs)[len(xs)//2]\n"})
    (root / "app.py").write_text(
        "def median(xs):\n"
        "    xs = sorted(xs)\n"
        "    n = len(xs)\n"
        "    SENTINEL_FIX_BODY = True\n"
        "    return (xs[n//2-1] + xs[n//2]) / 2 if n % 2 == 0 else xs[n//2]\n"
    )
    (root / "helper.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        [
            "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
            "-m", "added median fix for even-length lists\n\nalso added a helper file",
        ],
        cwd=root,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_prompt_instructs_rather_than_reports(tmp_path: Path) -> None:
    sha = _repo_with_change(tmp_path)
    title, prompt = commit_task_description(tmp_path, sha)

    # Title stays the raw subject — it is a label, not an instruction.
    assert title == "added median fix for even-length lists"

    lowered = prompt.lower()
    assert "implement" in lowered
    # The agent must be told the work is outstanding, or it acknowledges and exits.
    assert "not been applied" in lowered
    assert "editing files" in lowered or "edit" in lowered
    # And the original description is still carried verbatim (spec §8.2).
    assert "added median fix for even-length lists" in prompt
    assert "also added a helper file" in prompt


def test_changed_paths_are_orientation(tmp_path: Path) -> None:
    sha = _repo_with_change(tmp_path)
    _, prompt = commit_task_description(tmp_path, sha)
    assert "app.py" in prompt
    assert "helper.py" in prompt


def test_prompt_never_contains_the_solution(tmp_path: Path) -> None:
    """Paths orient; hunks would hand over the answer."""
    sha = _repo_with_change(tmp_path)
    _, prompt = commit_task_description(tmp_path, sha)

    # A distinctive token from the fixed body must not appear anywhere.
    assert "SENTINEL_FIX_BODY" not in prompt
    # Nor diff syntax.
    assert "@@" not in prompt
    assert "+++" not in prompt
    assert "diff --git" not in prompt


def test_survives_a_commit_with_no_body(tmp_path: Path) -> None:
    make_git_repo(tmp_path, {"a.txt": "x"})
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    title, prompt = commit_task_description(tmp_path, sha)
    assert title == "init"
    assert "implement" in prompt.lower()
