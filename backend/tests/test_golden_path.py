"""The golden path: a run's workspace is a leakage-proof snapshot at the
task's BASE commit, and grading uses the repository's real commands.

Before this wiring existed the queue copied `config["fixture_path"]` verbatim
and ignored `task.base_commit` entirely, so historical replay silently graded
the wrong tree and every regression check compared against an empty baseline.
These tests are what keep that from regressing.
"""

import asyncio
import subprocess
from pathlib import Path

import httpx
import pytest

from app.api.routes import derive_config
from app.db.engine import SessionLocal
from app.main import create_app
from app.models import BaselineResult, BenchmarkTask, Repository, RepositoryCommand
from app.orchestration.queue import materialize_workspace
from tests.test_repo_service import make_git_repo


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo_with_solution(tmp_path: Path) -> tuple[Path, str, str]:
    """Repo whose HEAD commit is 'the answer'; returns (root, base_sha, head_sha)."""
    root = tmp_path / "repo"
    make_git_repo(root, {"app.py": "def f():\n    return 1\n"})
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    (root / "SOLUTION.txt").write_text("the answer")
    (root / "app.py").write_text("def f():\n    return 2\n")
    head = _commit(root, "fix f()")
    return root, base, head


# --- workspace construction -------------------------------------------------


def test_workspace_is_snapshot_at_base_commit_without_the_solution(tmp_path: Path) -> None:
    root, base, _head = _repo_with_solution(tmp_path)
    repo = Repository(name="r", source="local", path_or_url=str(root))
    task = BenchmarkTask(
        repository_id="x", kind="commit", title="t", prompt="p", base_commit=base
    )

    dest = tmp_path / "ws"
    materialize_workspace(task, repo, {}, dest)

    # The solution must not be reachable from inside the sandbox, in any form.
    assert not (dest / "SOLUTION.txt").exists()
    assert (dest / "app.py").read_text() == "def f():\n    return 1\n"

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=dest, capture_output=True, text=True
    ).stdout
    assert len(log.strip().splitlines()) == 1, "original history leaked into the workspace"
    remotes = subprocess.run(
        ["git", "remote"], cwd=dest, capture_output=True, text=True
    ).stdout
    assert remotes.strip() == "", "a remote would let the agent fetch the answer"


def test_workspace_falls_back_to_fixture_when_task_has_no_base_commit(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.txt").write_text("hi")
    task = BenchmarkTask(repository_id="x", kind="user_defined", title="t", prompt="p")

    dest = tmp_path / "ws"
    materialize_workspace(task, None, {"fixture_path": str(fixture)}, dest)
    assert (dest / "a.txt").read_text() == "hi"


def test_workspace_refuses_when_there_is_nothing_to_build_from(tmp_path: Path) -> None:
    task = BenchmarkTask(repository_id="x", kind="user_defined", title="t", prompt="p")
    with pytest.raises(RuntimeError, match="neither a base commit nor a fixture_path"):
        materialize_workspace(task, None, {}, tmp_path / "ws")


# --- config derivation ------------------------------------------------------


def test_derive_config_supplies_real_commands_and_baseline_cases() -> None:
    with SessionLocal() as session:
        repo = Repository(name="r", source="local", path_or_url="/tmp/r")
        session.add(repo)
        session.flush()
        session.add(
            RepositoryCommand(
                repository_id=repo.id,
                install="npm ci",
                test="npm test",
                lint=None,
                test_framework="vitest",
            )
        )
        session.add(
            BaselineResult(
                repository_id=repo.id,
                base_commit="abc",
                benchmarkable=True,
                test_cases=[["a.test.ts::x", "passed"], ["a.test.ts::y", "failed"]],
            )
        )
        session.commit()

        derived = derive_config(session, repo.id)

    # A JS repo must not be graded with the hardcoded pytest fallback.
    assert derived["commands"] == {"install": "npm ci", "test": "npm test"}
    assert derived["test_framework"] == "vitest"
    # Pre-existing failures must be known, else they count as agent regressions.
    assert ["a.test.ts::y", "failed"] in derived["baseline_cases"]


def test_derive_config_omits_unset_commands() -> None:
    with SessionLocal() as session:
        repo = Repository(name="r2", source="local", path_or_url="/tmp/r2")
        session.add(repo)
        session.flush()
        session.add(RepositoryCommand(repository_id=repo.id, test="pytest"))
        session.commit()
        derived = derive_config(session, repo.id)
    assert derived["commands"] == {"test": "pytest"}


# --- end to end -------------------------------------------------------------


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    app = create_app(start_worker=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_from_commit_run_grades_against_a_snapshot(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root, base, head = _repo_with_solution(tmp_path)

    repo = (
        await client.post(
            "/api/v1/repositories",
            json={"name": "gp", "source": "local", "path_or_url": str(root)},
        )
    ).json()
    task = (
        await client.post(
            "/api/v1/tasks/from-commit", json={"repository_id": repo["id"], "sha": head}
        )
    ).json()
    assert task["base_commit"] == base

    exp = (
        await client.post(
            "/api/v1/experiments",
            json={
                "repository_id": repo["id"],
                "name": "golden",
                "task_ids": [task["id"]],
                "combinations": [
                    {"harness": "fake", "provider": "fake", "model_id": "fake/deterministic-1:free"}
                ],
                "repetitions": 1,
                # Deterministic evaluator command — the point here is the
                # snapshot wiring, not a real test runner.
                "config": {
                    "commands": {"test": "echo 'app.py::t1 PASSED'"},
                    "test_framework": "pytest",
                },
            },
        )
    ).json()

    for _ in range(100):
        status = (await client.get(f"/api/v1/experiments/{exp['id']}")).json()
        if status["runs"]["by_state"].get("COMPLETED") == status["runs"]["total"]:
            break
        await asyncio.sleep(0.1)
    assert status["runs"]["by_state"].get("COMPLETED") == 1

    from sqlalchemy import select

    from app.models import EvaluationResult

    with SessionLocal() as session:
        evaluation = session.scalars(
            select(EvaluationResult).order_by(EvaluationResult.created_at.desc())
        ).first()

    assert evaluation is not None
    # The old code path returned this whenever fixture_path was absent, which
    # is exactly what a real historical task looks like.
    assert evaluation.signal != "no_evaluation_configured"
    assert evaluation.results.get("apply", {}).get("ok") is True
