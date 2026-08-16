from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import (
    live,
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


def _install_provider() -> str:
    """Register every provider that has a key; the first becomes the default.

    Runs route by their own combination's provider, so several can be live at
    once. Without any key the proxy keeps its FakeProvider, which is what the
    test suite and `make demo` rely on — otherwise a run that looks real would
    never reach a model at all.
    """
    from app.api.proxy import register_provider, set_provider
    from app.core.config import settings

    installed: list[str] = []

    if settings.openrouter_api_key:
        from app.providers.openrouter import OpenRouterProvider

        set_provider(
            OpenRouterProvider(
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                http_referer=settings.openrouter_http_referer,
                app_name=settings.openrouter_app_name,
            )
        )
        installed.append("openrouter")

    if settings.nvidia_api_key:
        from app.providers.nim import NimProvider

        nim = NimProvider(
            api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url
        )
        # Default only if it is the sole configured provider.
        (register_provider if installed else set_provider)(nim)
        installed.append("nvidia")

    if settings.anthropic_api_key:
        from app.providers.anthropic import AnthropicProvider

        anthropic = AnthropicProvider(
            api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url
        )
        (register_provider if installed else set_provider)(anthropic)
        installed.append("anthropic")

    if settings.openai_api_key:
        from app.providers.openai_api import OpenAIProvider

        openai = OpenAIProvider(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url
        )
        (register_provider if installed else set_provider)(openai)
        installed.append("openai")

    return "+".join(installed) or "fake"


def create_app(start_worker: bool = True) -> FastAPI:
    setup_logging()
    ensure_schema()
    provider_name = _install_provider()

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
    app.state.provider_name = provider_name
    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(repos_analysis.router, prefix="/api/v1")
    app.include_router(providers_api.router, prefix="/api/v1")
    app.include_router(run_control.router, prefix="/api/v1")
    app.include_router(tasks_api.router, prefix="/api/v1")
    app.include_router(results_api.router, prefix="/api/v1")
    app.include_router(live.router, prefix="/api/v1")
    app.include_router(proxy.router, prefix="/proxy")
    return app


app = create_app()
