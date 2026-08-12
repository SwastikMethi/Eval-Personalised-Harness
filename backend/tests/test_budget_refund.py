"""A request that returned nothing must not consume the run's step budget.

Measured on a real run: deepseek-v4-flash got 8 requests, two of which were
504s from NIM's gateway at 302s. It therefore had 6 usable steps rather than
the 8 it was promised — our infrastructure quietly making one model look worse
than another in a tool built to compare them fairly.

The refund must not become free spend, so the ceilings are asserted here too.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException

from app.api import proxy
from app.core.errors import ErrorCategory
from app.providers.base import CompletionResult, CompletionUsage, ModelInfo, ModelProvider
from app.providers.fake import FakeProvider
from app.providers.openrouter import ProviderError

MODEL = "fake/deterministic-1:free"


class GatewayTimeout(ModelProvider):
    """NIM's 504 after 302s — the model was still generating."""

    name = "gateway-timeout"

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def validate_model(self, model_id: str) -> ModelInfo:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": False}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        raise ProviderError(
            "provider error (504): ", ErrorCategory.MODEL_PROVIDER, retryable=True, status=504
        )


class NotEnabled(GatewayTimeout):
    """404: the model is in the catalog but not enabled for this account."""

    name = "not-enabled"

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        raise ProviderError(
            "provider rejected request (404): Function 'e503b15c': Not found for account",
            ErrorCategory.MODEL_PROVIDER,
            retryable=False,
            status=404,
        )


class Expensive(GatewayTimeout):
    name = "expensive"

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        return CompletionResult(
            content="ok",
            usage=CompletionUsage(input_tokens=1000, output_tokens=1000, cached_tokens=0),
            raw={},
            message={"role": "assistant", "content": "ok"},
            finish_reason="stop",
        )


@pytest.fixture
def restore_provider() -> Iterator[None]:
    yield
    proxy.set_provider(FakeProvider())


def body() -> Any:
    return proxy.ChatRequest(model=MODEL, messages=[{"role": "user", "content": "hi"}])


async def test_a_failed_request_is_refunded(restore_provider: None) -> None:
    proxy.set_provider(GatewayTimeout())
    token = proxy.issue_run_token("refund-run", MODEL, max_requests=3)

    for _ in range(5):  # more attempts than the budget
        with pytest.raises(HTTPException):
            await proxy.chat_completions(body(), authorization=f"Bearer {token}")

    usage = proxy.run_usage("refund-run")
    assert usage["requests"] == 0, "nothing usable came back, so nothing is charged"
    assert usage["attempted"] == 5, "attempts stay visible — the refund hides nothing"
    assert usage["budget_exhausted"] is False
    proxy.revoke_run_token("refund-run")


async def test_a_successful_request_is_charged(restore_provider: None) -> None:
    proxy.set_provider(FakeProvider())
    token = proxy.issue_run_token("charge-run", MODEL, max_requests=2)

    await proxy.chat_completions(body(), authorization=f"Bearer {token}")
    assert proxy.run_usage("charge-run")["requests"] == 1

    await proxy.chat_completions(body(), authorization=f"Bearer {token}")
    usage = proxy.run_usage("charge-run")
    assert usage["requests"] == 2
    assert usage["budget_exhausted"] is True

    with pytest.raises(Exception) as exc:
        await proxy.chat_completions(body(), authorization=f"Bearer {token}")
    assert getattr(exc.value, "status_code", None) == 429
    proxy.revoke_run_token("charge-run")


async def test_the_spend_ceiling_still_bounds_a_refunded_run(restore_provider: None) -> None:
    """The refund must not turn into unlimited spend: tokens and cost accrue on
    every successful call regardless of the request count."""
    proxy.set_provider(Expensive())
    token = proxy.issue_run_token(
        "ceiling-run", MODEL, max_requests=100, max_cost_usd=0.0001,
        input_price=1e-6, output_price=1e-6,
    )
    await proxy.chat_completions(body(), authorization=f"Bearer {token}")

    with pytest.raises(Exception) as exc:
        await proxy.chat_completions(body(), authorization=f"Bearer {token}")
    assert getattr(exc.value, "status_code", None) == 429
    proxy.revoke_run_token("ceiling-run")


async def test_a_permanent_rejection_is_marked_non_retryable(restore_provider: None) -> None:
    """404 means this model will never work here. The queue must be able to
    tell that from a 504, which is worth waiting out."""
    proxy.set_provider(NotEnabled())
    token = proxy.issue_run_token("404-run", MODEL, max_requests=3)

    with pytest.raises(HTTPException):
        await proxy.chat_completions(body(), authorization=f"Bearer {token}")

    usage = proxy.run_usage("404-run")
    assert usage["provider_error"] is True
    assert usage["provider_error_retryable"] is False
    proxy.revoke_run_token("404-run")


async def test_a_gateway_timeout_stays_retryable(restore_provider: None) -> None:
    proxy.set_provider(GatewayTimeout())
    token = proxy.issue_run_token("504-run", MODEL, max_requests=3)

    with pytest.raises(HTTPException):
        await proxy.chat_completions(body(), authorization=f"Bearer {token}")

    usage = proxy.run_usage("504-run")
    assert usage["provider_error"] is True
    assert usage["provider_error_retryable"] is True
    proxy.revoke_run_token("504-run")
