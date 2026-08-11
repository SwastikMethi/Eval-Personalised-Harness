"""`make demo`: seed the fixture and run a full skeleton experiment with fakes.

Zero API cost — FakeHarness calls the proxy, FakeProvider answers.
"""

import asyncio
import sys
import time
from pathlib import Path

import httpx

from app.main import create_app

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "python-bug-repo"


async def main() -> int:
    app = create_app(start_worker=True)
    # create_app installs OpenRouterProvider whenever a key is configured, but
    # this demo is documented as zero API cost and uses a fake model id that a
    # real provider rightly rejects. Force the fake back so `make demo` never
    # spends quota — free tier grants ~50 requests a DAY (ADR-003).
    from app.api.proxy import set_provider
    from app.providers.fake import FakeProvider

    set_provider(FakeProvider())
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=transport, base_url="http://aso.local"
    ) as client:
        repo = (
            await client.post(
                "/api/v1/repositories",
                json={"name": "python-bug-repo", "source": "local", "path_or_url": str(FIXTURE)},
            )
        ).json()
        task = (
            await client.post(
                "/api/v1/tasks",
                json={
                    "repository_id": repo["id"],
                    "title": "Fix median() for even-length lists",
                    "prompt": "median() returns the wrong value for even-length lists; fix it.",
                },
            )
        ).json()
        exp = (
            await client.post(
                "/api/v1/experiments",
                json={
                    "repository_id": repo["id"],
                    "name": "demo",
                    "task_ids": [task["id"]],
                    "combinations": [
                        {
                            "harness": "fake",
                            "provider": "fake",
                            "model_id": "fake/deterministic-1:free",
                        }
                    ],
                    "repetitions": 2,
                    "config": {"fixture_path": str(FIXTURE)},
                },
            )
        ).json()
        print(f"experiment {exp['id']}: {exp['runs']} runs queued")

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = (await client.get(f"/api/v1/experiments/{exp['id']}")).json()
            by_state = status["runs"]["by_state"]
            print(f"  states: {by_state}")
            if by_state.get("COMPLETED", 0) == status["runs"]["total"]:
                print("demo complete: all runs COMPLETED")
                return 0
            if by_state.get("FAILED"):
                print("demo FAILED")
                return 1
            await asyncio.sleep(0.5)
        print("demo timed out")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
