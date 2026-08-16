"""A comprehension run must not build the repo's dependencies.

A theory task is graded by rubric: the agent reads the repository and writes an
answer. It never applies a patch and never runs a suite, so installing the
repo's dependencies buys the run nothing — and on a repo whose install does not
work inside the sandbox, it buys minutes of failing before the same answer.

This is also what makes comprehension the mode that still works on a repo the
harness cannot otherwise baseline.
"""

from pathlib import Path

from app.orchestration.queue import QueueWorker

CONFIG = {"commands": {"install": "make setup"}}


def test_theory_task_asks_for_no_prepared_image(tmp_path: Path) -> None:
    assert QueueWorker._prepared_image(tmp_path, CONFIG, "repo1", "theory") is None


def test_commit_task_still_wants_one(tmp_path: Path, monkeypatch) -> None:
    """The saving must be specific to theory, not a blanket disable."""
    built: list[str] = []

    monkeypatch.setattr("app.sandboxes.manager.docker_available", lambda: True)
    monkeypatch.setattr(
        "app.sandboxes.prepared.ensure_prepared_image",
        lambda root, cmd, repo_id: (built.append(cmd) or ("aso-prepared:x", None)),
    )

    image = QueueWorker._prepared_image(tmp_path, CONFIG, "repo1", "commit")

    assert image == "aso-prepared:x"
    assert built == ["make setup"]


def test_no_install_command_means_the_base_image(tmp_path: Path) -> None:
    assert QueueWorker._prepared_image(tmp_path, {"commands": {}}, "repo1", "commit") is None
