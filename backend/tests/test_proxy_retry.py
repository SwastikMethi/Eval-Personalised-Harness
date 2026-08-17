"""The proxy retries a flaky provider so one 5xx does not end a whole run.

nvidia/nemotron-3-ultra-550b-a55b returns a sub-second 503 for roughly one
request in seven. A harness has no retry of its own, so before this the first
503 killed the run and the failure was recorded against the harness.
"""

from typing import Any

import httpx
import pytest

from app.api import proxy
from app.core.errors import ErrorCategory
from app.main import create_app
from app.providers.base import CompletionResult, CompletionUsage, ModelProvider
from app.providers.openrouter import ProviderError

MODEL = "fake/deterministic-1:free"


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    app = create_app(start_worker=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class FlakyProvider(ModelProvider):
    """Fails `failures` times with the given error, then answers."""

    name = "flaky"

    def __init__(self, failures: int, exc: ProviderError) -> None:
        self.calls = 0
        self._failures = failures
        self._exc = exc

    async def list_models(self) -> list[Any]:
        return []

    async def validate_model(self, model_id: str) -> Any:
        return None

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        self.calls += 1
        if self.calls <= self._failures:
            raise self._exc
        return CompletionResult(
            content="recovered",
            usage=CompletionUsage(input_tokens=3, output_tokens=1, cached_tokens=0),
            raw={"model": model_id},
        )


def _503() -> ProviderError:
    return ProviderError(
        "provider error (503)", ErrorCategory.MODEL_PROVIDER, retryable=True, status=503
    )


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proxy, "PROVIDER_RETRY_BACKOFF_S", (0.0, 0.0))


def _install(monkeypatch: pytest.MonkeyPatch, provider: ModelProvider) -> None:
    monkeypatch.setattr(proxy, "provider_for", lambda _name: provider)


async def _post(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(
        "/proxy/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )


async def test_transient_503_is_retried(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FlakyProvider(failures=2, exc=_503())
    _install(monkeypatch, provider)
    token = proxy.issue_run_token("run-retry-ok", MODEL)
    try:
        resp = await _post(client, token)
        assert resp.status_code == 200, resp.text
        assert provider.calls == 3
        # The agent made one request and got one answer; it is charged once.
        assert proxy.run_usage("run-retry-ok")["requests"] == 1
    finally:
        proxy.revoke_run_token("run-retry-ok")


async def test_retries_are_capped(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FlakyProvider(failures=99, exc=_503())
    _install(monkeypatch, provider)
    token = proxy.issue_run_token("run-retry-give-up", MODEL)
    try:
        resp = await _post(client, token)
        assert resp.status_code == 502
        assert provider.calls == proxy.PROVIDER_RETRY_ATTEMPTS + 1
        usage = proxy.run_usage("run-retry-give-up")
        # Refunded exactly once on the give-up path, not once per attempt.
        assert usage["requests"] == 0
        assert usage["provider_error"] is True
    finally:
        proxy.revoke_run_token("run-retry-give-up")


async def test_rate_limit_is_not_retried(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 keeps its own path — retrying inline spends quota fighting a limit."""
    exc = ProviderError(
        "rate limited (429)", ErrorCategory.RATE_LIMITED, retryable=True, status=429
    )
    provider = FlakyProvider(failures=99, exc=exc)
    _install(monkeypatch, provider)
    token = proxy.issue_run_token("run-retry-429", MODEL)
    try:
        resp = await _post(client, token)
        assert resp.status_code == 429
        assert provider.calls == 1
    finally:
        proxy.revoke_run_token("run-retry-429")


async def test_every_attempt_is_recorded(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently swallowing the failed attempts would hide provider flakiness."""
    from sqlalchemy import select

    from app.db.engine import SessionLocal
    from app.models import ModelRequestMetric

    provider = FlakyProvider(failures=1, exc=_503())
    _install(monkeypatch, provider)
    token = proxy.issue_run_token("run-retry-metrics", MODEL)
    try:
        assert (await _post(client, token)).status_code == 200
    finally:
        proxy.revoke_run_token("run-retry-metrics")

    with SessionLocal() as session:
        metrics = session.scalars(
            select(ModelRequestMetric).where(
                ModelRequestMetric.run_id == "run-retry-metrics"
            )
        ).all()
    assert sorted(m.http_status for m in metrics) == [200, 503]
