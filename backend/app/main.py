from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import (
    providers_api,
    proxy,
    repos_analysis,
    results_api,
    routes,
    run_control,
    tasks_api,
)
from app.core.logging import setup_logging
from app.db.engine import SessionLocal, ensure_schema
from app.harnesses.base import register
from app.harnesses.fake import FakeHarness
from app.orchestration.queue import QueueWorker
from app.orchestration.recovery import reconcile


def create_app(start_worker: bool = True) -> FastAPI:
    setup_logging()
    ensure_schema()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker: QueueWorker | None = None
        if start_worker:
            # Crash reconciliation before scheduling anything (eng review 2A).
            reconcile(SessionLocal)
            # In-process ASGI transport: the FakeHarness proxy call exercises the
            # real HTTP protocol without requiring the socket to be up first.
            register(FakeHarness(transport=httpx.ASGITransport(app=app)))
            sandboxes = None
            from app.sandboxes.manager import SandboxManager, docker_available

            if docker_available():
                sandboxes = SandboxManager()
                from app.harnesses.mini_swe_agent import MiniSweAgentHarness
                from app.harnesses.smolagents_agent import SmolagentsHarness

                register(MiniSweAgentHarness(sandboxes))
                register(SmolagentsHarness(sandboxes))
            worker = QueueWorker(
                SessionLocal,
                proxy_base_url="http://aso.local/proxy",
                sandbox_manager=sandboxes,
            )
            worker.start()
            app.state.worker = worker
        yield
        if worker:
            await worker.stop()

    app = FastAPI(title="Agent Stack Optimizer", lifespan=lifespan)
    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(repos_analysis.router, prefix="/api/v1")
    app.include_router(providers_api.router, prefix="/api/v1")
    app.include_router(run_control.router, prefix="/api/v1")
    app.include_router(tasks_api.router, prefix="/api/v1")
    app.include_router(results_api.router, prefix="/api/v1")
    app.include_router(proxy.router, prefix="/proxy")
    return app


app = create_app()
