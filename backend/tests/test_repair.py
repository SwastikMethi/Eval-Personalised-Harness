"""Test-environment repair, and the boundary that keeps it honest.

Two properties matter here and nothing else really does:

1. A repair may never touch application source. Repairing `src/` would fix the
   bug the agent is asked to fix, so every harness would score full marks on a
   task that no longer exists. The allowlist is enforced on the returned diff,
   because a model cannot be trusted to respect a boundary that decides whether
   the benchmark measures anything.

2. Whatever the repair changes must reach the agent's workspace and the graded
   tree identically. If those diverge nothing errors — the scores just stop
   being about the same repository.
"""

import subprocess
from pathlib import Path

import pytest

from app.repositories.repair import (
    RepairError,
    apply_patch,
    disallowed_paths,
    extract_diff,
    patched_paths,
)
from tests.test_repo_service import make_git_repo


def diff_touching(*paths: str) -> str:
    """A minimal but structurally real unified diff over the given paths."""
    chunks = []
    for path in paths:
        chunks += [
            f"diff --git a/{path} b/{path}",
            "--- a/" + path,
            "+++ b/" + path,
            "@@ -1 +1,2 @@",
            " existing",
            "+added",
        ]
    return "\n".join(chunks) + "\n"


# --- the boundary -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "requirements.txt",
        "requirements-dev.txt",
        "requirements.in",
        "pyproject.toml",
        "setup.cfg",
        "pytest.ini",
        "tox.ini",
        "conftest.py",
        "tests/conftest.py",
        "package.json",
        "tests/test_data_loader.py",
        "src/thing_test.py",
        "app/__tests__/x.spec.ts",
    ],
)
def test_configuration_and_test_files_are_allowed(path: str) -> None:
    assert disallowed_paths(diff_touching(path)) == []


@pytest.mark.parametrize(
    "path",
    [
        "src/server.py",
        "src/resources/pokemon_data.py",
        "app/main.py",
        "Makefile",
        ".github/workflows/ci.yml",
        "README.md",
    ],
)
def test_application_source_is_refused(path: str) -> None:
    """The bug lives in src/. Repairing it there deletes the task."""
    assert disallowed_paths(diff_touching(path)) == [path]


def test_path_traversal_is_refused() -> None:
    """A diff is untrusted input; `../` would write outside the snapshot."""
    assert disallowed_paths(diff_touching("../../etc/passwd")) != []


def test_one_bad_path_rejects_the_whole_patch() -> None:
    """Filtering hunks would leave a partly-applied tree nobody reviewed."""
    mixed = diff_touching("requirements.txt", "src/server.py")
    assert disallowed_paths(mixed) == ["src/server.py"]


def test_paths_are_read_from_both_the_header_and_the_hunks() -> None:
    """A patch that names one file in `diff --git` and another in `+++` must
    not sneak the second past the allowlist."""
    sneaky = (
        "diff --git a/requirements.txt b/requirements.txt\n"
        "--- a/requirements.txt\n"
        "+++ b/src/server.py\n"
        "@@ -1 +1,2 @@\n"
        " x\n"
        "+y\n"
    )
    assert "src/server.py" in patched_paths(sneaky)
    assert disallowed_paths(sneaky) == ["src/server.py"]


# --- extraction -------------------------------------------------------------


def test_fenced_diff_is_extracted() -> None:
    body = extract_diff("Sure:\n```diff\n" + diff_touching("pytest.ini") + "```\n")
    assert body.startswith("diff --git a/pytest.ini")


def test_no_safe_repair_is_a_valid_answer() -> None:
    with pytest.raises(RepairError, match="no safe repair"):
        extract_diff("NO_SAFE_REPAIR")


def test_prose_is_not_a_diff() -> None:
    with pytest.raises(RepairError, match="did not return a unified diff"):
        extract_diff("You should probably install pytest-asyncio.")


# --- both trees, or neither -------------------------------------------------


def test_the_fixup_reaches_the_agent_tree_and_the_graded_tree_alike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """materialize_workspace builds BOTH trees, so applying the fixup inside it
    is what makes divergence impossible rather than merely unlikely. This test
    fails the moment someone moves the call out to one of the two call sites.
    """
    from app.core.config import settings
    from app.models import BenchmarkTask, Repository
    from app.orchestration.queue import materialize_workspace
    from app.repositories import repair

    source = tmp_path / "src-repo"
    make_git_repo(source, {"requirements.txt": "requests\n", "src/app.py": "x = 1\n"})
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True
    ).stdout.strip()

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)
    repo = Repository(id="repo-xyz", name="r", source="local", path_or_url=str(source))
    task = BenchmarkTask(
        id="task-xyz", repository_id=repo.id, kind="commit", title="t", prompt="p",
        base_commit=base,
    )
    repair.save_fixup(
        repo.id,
        "--- a/requirements.txt\n"
        "+++ b/requirements.txt\n"
        "@@ -1 +1,2 @@\n"
        " requests\n"
        "+pytest-asyncio\n",
    )

    agent_tree = tmp_path / "agent"
    graded_tree = tmp_path / "graded"
    materialize_workspace(task, repo, {}, agent_tree)
    materialize_workspace(task, repo, {}, graded_tree)

    agent_reqs = (agent_tree / "requirements.txt").read_text()
    graded_reqs = (graded_tree / "requirements.txt").read_text()
    assert "pytest-asyncio" in agent_reqs
    assert agent_reqs == graded_reqs
    # And the repair did not smuggle in a source change.
    assert (agent_tree / "src" / "app.py").read_text() == "x = 1\n"


def test_no_fixup_leaves_the_snapshot_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.models import BenchmarkTask, Repository
    from app.orchestration.queue import materialize_workspace

    source = tmp_path / "src-repo"
    make_git_repo(source, {"requirements.txt": "requests\n"})
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True
    ).stdout.strip()

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)
    repo = Repository(id="repo-none", name="r", source="local", path_or_url=str(source))
    task = BenchmarkTask(
        id="task-none", repository_id=repo.id, kind="commit", title="t", prompt="p",
        base_commit=base,
    )

    dest = tmp_path / "ws"
    materialize_workspace(task, repo, {}, dest)
    assert (dest / "requirements.txt").read_text() == "requests\n"


def test_apply_patch_reports_a_conflict_rather_than_half_applying(tmp_path: Path) -> None:
    make_git_repo(tmp_path, {"requirements.txt": "totally-different\n"})
    ok, err = apply_patch(
        tmp_path,
        "--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1 +1,2 @@\n requests\n+pytest\n",
    )
    assert not ok
    assert err
