"""Endpoints the UI depends on: harness listing, matrix preview, live progress,
run detail, patch retrieval, experiment cancel (spec §19, §20).
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


async def _experiment(client: httpx.AsyncClient, reps: int = 1) -> tuple[str, str]:
    repo = (
        await client.post(
            "/api/v1/repositories",
            json={"name": "live", "source": "local", "path_or_url": str(FIXTURE)},
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
                "name": "live",
                "task_ids": [task["id"]],
                "combinations": [
                    {"harness": "fake", "provider": "fake", "model_id": "fake/deterministic-1:free"}
                ],
                "repetitions": reps,
                "config": {"fixture_path": str(FIXTURE)},
            },
        )
    ).json()
    return exp["id"], task["id"]


async def _await_finish(client: httpx.AsyncClient, exp_id: str) -> dict:
    for _ in range(120):
        progress = (await client.get(f"/api/v1/experiments/{exp_id}/progress")).json()
        if progress["finished"]:
            return progress
        await asyncio.sleep(0.1)
    return progress


async def test_harnesses_are_discovered_not_hardcoded(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/harnesses")).json()
    names = {h["name"] for h in body}
    assert "fake" in names
    # The UI needs to know which ones require Docker + a proxy token.
    assert all("sandboxed" in h for h in body)
    assert next(h for h in body if h["name"] == "fake")["sandboxed"] is False


async def test_preview_reports_the_expanded_run_count(client: httpx.AsyncClient) -> None:
    body = (
        await client.post(
            "/api/v1/experiments/preview",
            json={
                "task_ids": ["a", "b", "c"],
                "harnesses": ["mini-swe-agent", "smolagents"],
                "model_ids": ["m1", "m2", "m3"],
                "repetitions": 3,
            },
        )
    ).json()
    assert body["runs"] == 54
    assert body["combinations"] == 6
    assert "2 harnesses × 3 models × 3 tasks × 3 reps = 54 runs" == body["expression"]


async def test_preview_counts_hand_picked_stacks_without_crossing_them(
    client: httpx.AsyncClient,
) -> None:
    """Two chosen pairs are two stacks, not the four a grid would produce.

    `POST /experiments` has always taken an arbitrary combination list; preview
    was the last place that assumed a full grid, so it would have reported 4
    for a matrix the server was about to queue as 2.
    """
    body = (
        await client.post(
            "/api/v1/experiments/preview",
            json={
                "task_ids": ["a", "b"],
                "combinations": [
                    {"harness": "mini-swe-agent", "provider": "nvidia", "model_id": "nemotron"},
                    {"harness": "smolagents", "provider": "openrouter", "model_id": "gpt-oss"},
                ],
                "repetitions": 3,
            },
        )
    ).json()

    assert body["combinations"] == 2, "crossing them would have given 4"
    assert body["runs"] == 12
    assert body["expression"] == "2 stacks × 2 tasks × 3 reps = 12 runs"


async def test_preview_counts_one_model_on_two_providers_as_two_stacks(
    client: httpx.AsyncClient,
) -> None:
    """The provider is part of a stack's identity, not incidental to it."""
    body = (
        await client.post(
            "/api/v1/experiments/preview",
            json={
                "task_ids": ["a"],
                "combinations": [
                    {"harness": "mini-swe-agent", "provider": "nvidia", "model_id": "same-model"},
                    {
                        "harness": "mini-swe-agent",
                        "provider": "openrouter",
                        "model_id": "same-model",
                    },
                ],
                "repetitions": 1,
            },
        )
    ).json()
    assert body["combinations"] == 2
    assert body["runs"] == 2


async def test_progress_exposes_per_run_rows_for_the_live_screen(
    client: httpx.AsyncClient,
) -> None:
    exp_id, _ = await _experiment(client)
    progress = await _await_finish(client, exp_id)

    assert progress["total"] == 1
    assert progress["done"] == 1
    row = progress["runs"][0]
    # Everything the live screen renders per row.
    for key in ("run_id", "harness", "model_id", "state", "elapsed_s", "model_requests"):
        assert key in row
    assert row["harness"] == "fake"


async def test_sse_stream_emits_progress_then_done(client: httpx.AsyncClient) -> None:
    exp_id, _ = await _experiment(client)
    seen: list[str] = []
    async with client.stream("GET", f"/api/v1/experiments/{exp_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                seen.append(line.removeprefix("event: ").strip())
            if seen and seen[-1] == "done":
                break
    assert "progress" in seen
    assert seen[-1] == "done"


async def test_sse_replays_history_so_a_late_viewer_sees_everything(
    client: httpx.AsyncClient,
) -> None:
    exp_id, _ = await _experiment(client)
    await _await_finish(client, exp_id)

    # Connect only AFTER the experiment finished.
    run_events: list[str] = []
    async with client.stream("GET", f"/api/v1/experiments/{exp_id}/events") as response:
        async for line in response.aiter_lines():
            if line.startswith("event: run"):
                run_events.append(line)
            if line.startswith("event: done"):
                break
    # Events are persisted, not an in-memory bus, so nothing is missed.
    assert run_events, "a late viewer should still receive the run history"


async def test_run_detail_and_patch(client: httpx.AsyncClient) -> None:
    exp_id, _ = await _experiment(client)
    progress = await _await_finish(client, exp_id)
    run_id = progress["runs"][0]["run_id"]

    detail = (await client.get(f"/api/v1/runs/{run_id}/detail")).json()
    assert detail["harness"] == "fake"
    assert detail["task"]["title"] == "t"
    assert detail["timeline"], "run detail needs a status timeline"
    assert detail["model_requests"], "proxy metrics should be visible per run"

    if detail["has_patch"]:
        patch = (await client.get(f"/api/v1/runs/{run_id}/patch")).json()
        assert "AGENT_NOTES" in patch["patch"]
        assert len(patch["checksum"]) == 64


async def test_missing_patch_is_404_not_a_crash(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/runs/nope/patch")).status_code == 404
    assert (await client.get("/api/v1/runs/nope/detail")).status_code == 404


async def test_experiment_status_settles_when_all_runs_finish(
    client: httpx.AsyncClient,
) -> None:
    """Status was set to "running" at creation and never updated, so finished
    experiments showed as running forever on the dashboard."""
    exp_id, _ = await _experiment(client)
    await _await_finish(client, exp_id)
    meta = (await client.get(f"/api/v1/experiments/{exp_id}")).json()
    assert meta["status"] == "completed"


async def test_cancel_experiment_stops_outstanding_runs(client: httpx.AsyncClient) -> None:
    exp_id, _ = await _experiment(client, reps=6)
    await client.post(f"/api/v1/experiments/{exp_id}/pause")
    body = (await client.post(f"/api/v1/experiments/{exp_id}/cancel")).json()
    assert body["ok"] is True

    progress = (await client.get(f"/api/v1/experiments/{exp_id}/progress")).json()
    assert progress["by_state"].get("CANCELLED", 0) >= 1
    # Already-terminal runs are left alone rather than illegally transitioned.
    assert progress["finished"] is True


async def test_comprehension_tasks_share_one_run_per_stack(
    client: httpx.AsyncClient,
) -> None:
    """The reported case: 3 stacks x 2 comprehension tasks gave 6 runs.

    Both tasks read the same HEAD snapshot, so six containers cloned the same
    repository and re-explored the same code. One run per stack is enough.
    """
    repo = (
        await client.post(
            "/api/v1/repositories",
            json={"name": "grouped", "source": "local", "path_or_url": str(FIXTURE)},
        )
    ).json()
    tasks = [
        (
            await client.post(
                "/api/v1/tasks",
                json={
                    "repository_id": repo["id"],
                    "kind": "theory",
                    "title": f"q{n}",
                    "prompt": "p",
                },
            )
        ).json()["id"]
        for n in (1, 2)
    ]

    created = await client.post(
        "/api/v1/experiments",
        json={
            "repository_id": repo["id"],
            "name": "grouped",
            "task_ids": tasks,
            "combinations": [
                {"harness": "fake", "provider": "fake", "model_id": "fake/deterministic-1:free"}
            ],
            "repetitions": 1,
            "config": {"fixture_path": str(FIXTURE)},
        },
    )
    assert created.status_code == 200, created.text
    # One stack, two tasks, one repetition: one run, not two.
    assert created.json()["runs"] == 1
