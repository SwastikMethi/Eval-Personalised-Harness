"""Walking-skeleton E2E: repo -> task -> experiment -> queue -> FakeHarness
(through the real proxy protocol) -> COMPLETED result. No Docker, no network.
"""

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


async def test_full_skeleton_run(client: httpx.AsyncClient) -> None:
    repo = (
        await client.post(
            "/api/v1/repositories",
            json={"name": "fixture", "source": "local", "path_or_url": str(FIXTURE)},
        )
    ).json()
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"repository_id": repo["id"], "title": "t", "prompt": "fix the bug"},
        )
    ).json()
    exp = (
        await client.post(
            "/api/v1/experiments",
            json={
                "repository_id": repo["id"],
                "name": "e2e",
                "task_ids": [task["id"]],
                "combinations": [
                    {"harness": "fake", "provider": "fake", "model_id": "fake/deterministic-1:free"}
                ],
                "repetitions": 2,
                "config": {"fixture_path": str(FIXTURE)},
            },
        )
    ).json()
    assert exp["runs"] == 2

    for _ in range(100):
        status = (await client.get(f"/api/v1/experiments/{exp['id']}")).json()
        by_state = status["runs"]["by_state"]
        if by_state.get("COMPLETED") == 2:
            break
        assert not by_state.get("FAILED"), f"run failed: {by_state}"
        await asyncio.sleep(0.1)
    else:
        pytest.fail(f"runs never completed: {by_state}")


async def test_proxy_rejects_bad_token(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/proxy/v1/chat/completions",
        headers={"Authorization": "Bearer bogus"},
        json={"model": "fake/deterministic-1:free", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 401


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/health")).json() == {"status": "ok"}
    assert (await client.get("/api/v1/ready")).json() == {"status": "ready"}
