from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import proxy, repos_analysis, routes
from app.core.logging import setup_logging
from app.db.engine import SessionLocal, engine
from app.harnesses.base import register
from app.harnesses.fake import FakeHarness
from app.models import Base
from app.orchestration.queue import QueueWorker


def create_app(start_worker: bool = True) -> FastAPI:
    setup_logging()
    Base.metadata.create_all(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker: QueueWorker | None = None
        if start_worker:
            # In-process ASGI transport: the FakeHarness proxy call exercises the
            # real HTTP protocol without requiring the socket to be up first.
            register(FakeHarness(transport=httpx.ASGITransport(app=app)))
            worker = QueueWorker(SessionLocal, proxy_base_url="http://aso.local/proxy")
            worker.start()
        yield
        if worker:
            await worker.stop()

    app = FastAPI(title="Agent Stack Optimizer", lifespan=lifespan)
    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(repos_analysis.router, prefix="/api/v1")
    app.include_router(proxy.router, prefix="/proxy")
    return app


app = create_app()
