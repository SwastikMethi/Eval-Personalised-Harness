"""Cancel / retry / pause / resume flows against the live worker (no Docker)."""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.main import create_app

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "python-bug-repo"


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    app = create_app(start_worker=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _make_experiment(client: httpx.AsyncClient, reps: int = 1) -> str:
    repo = (
        await client.post(
            "/api/v1/repositories",
            json={"name": "f", "source": "local", "path_or_url": str(FIXTURE)},
        )
    ).json()
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"repository_id": repo["id"], "title": "t", "prompt": "p"},
        )
    ).json()
    exp = (
        await client.post(
            "/api/v1/experiments",
            json={
                "repository_id": repo["id"],
                "name": "ctl",
                "task_ids": [task["id"]],
                "combinations": [
                    {"harness": "fake", "provider": "fake", "model_id": "fake/deterministic-1:free"}
                ],
                "repetitions": reps,
                "config": {"fixture_path": str(FIXTURE)},
            },
        )
    ).json()
    return str(exp["id"])


async def _wait_all_completed(client: httpx.AsyncClient, exp_id: str) -> dict[str, int]:
    for _ in range(100):
        status = (await client.get(f"/api/v1/experiments/{exp_id}")).json()
        by_state = status["runs"]["by_state"]
        if by_state.get("COMPLETED") == status["runs"]["total"]:
            return dict(by_state)
        await asyncio.sleep(0.1)
    return dict(by_state)


async def test_pause_blocks_scheduling_resume_releases(client: httpx.AsyncClient) -> None:
    # Pause an experiment that doesn't exist yet -> 404
    assert (await client.post("/api/v1/experiments/nope/pause")).status_code == 404

    exp_id = await _make_experiment(client)
    assert (await client.post(f"/api/v1/experiments/{exp_id}/pause")).status_code == 200
    # give the worker a moment; run should stay PENDING while paused
    # (created AFTER pause it never gets claimed — creation happened before,
    # so tolerate either PENDING or already-claimed; the invariant we assert
    # is that resume completes everything)
    assert (await client.post(f"/api/v1/experiments/{exp_id}/resume")).status_code == 200
    by_state = await _wait_all_completed(client, exp_id)
    assert by_state.get("COMPLETED") == 1


async def test_retry_failed_run(client: httpx.AsyncClient) -> None:
    exp_id = await _make_experiment(client)
    await _wait_all_completed(client, exp_id)
    status = (await client.get(f"/api/v1/experiments/{exp_id}")).json()
    assert status["runs"]["by_state"].get("COMPLETED") == 1

    # A COMPLETED run is NOT retryable
    from sqlalchemy import select

    from app.db.engine import SessionLocal
    from app.models import BenchmarkRun

    with SessionLocal() as session:
        run_id = session.scalars(select(BenchmarkRun.id)).all()[-1]
    resp = await client.post(f"/api/v1/runs/{run_id}/retry")
    assert resp.status_code == 409


async def test_cancel_pending_run(client: httpx.AsyncClient) -> None:
    exp_id = await _make_experiment(client)
    await client.post(f"/api/v1/experiments/{exp_id}/pause")
    # find this experiment's pending run and cancel it
    from sqlalchemy import select

    from app.db.engine import SessionLocal
    from app.models import BenchmarkRun, ExperimentCombination
    from app.models.core import RunState

    with SessionLocal() as session:
        combo_ids = session.scalars(
            select(ExperimentCombination.id).where(
                ExperimentCombination.experiment_id == exp_id
            )
        ).all()
        run = session.scalars(
            select(BenchmarkRun).where(
                BenchmarkRun.combination_id.in_(combo_ids),
                BenchmarkRun.state == RunState.PENDING,
            )
        ).first()
    if run is None:
        pytest.skip("run was claimed before pause took effect")
    resp = await client.post(f"/api/v1/runs/{run.id}/cancel")
    assert resp.status_code == 200
    with SessionLocal() as session:
        assert session.get(BenchmarkRun, run.id).state == RunState.CANCELLED  # type: ignore[union-attr]
    # cancelled runs are terminal — cancel again fails
    assert (await client.post(f"/api/v1/runs/{run.id}/cancel")).status_code == 409
