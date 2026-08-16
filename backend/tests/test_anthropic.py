"""Anthropic adapter: a genuinely different wire protocol, normalised.

Every test runs through httpx.MockTransport — no key, no network, no spend.
"""

from typing import Any

import httpx
import pytest

from app.core.errors import ErrorCategory
from app.providers.anthropic import API_VERSION, AnthropicProvider
from app.providers.openrouter import ProviderError

MODEL = "claude-sonnet-5"


def provider_with(handler: Any, api_key: str = "sk-ant-test") -> AnthropicProvider:
    return AnthropicProvider(api_key=api_key, transport=httpx.MockTransport(handler))


def messages_handler(request: httpx.Request) -> httpx.Response:
    messages_handler.seen = request  # type: ignore[attr-defined]
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "model": MODEL,
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        },
    )


async def test_completion_is_normalised_to_the_shared_shape() -> None:
    result = await provider_with(messages_handler).complete(
        MODEL, [{"role": "user", "content": "hi"}]
    )
    # Content blocks are concatenated, so callers never learn a second shape.
    assert result.content == "hello world"
    assert result.message == {"role": "assistant", "content": "hello world"}
    assert result.finish_reason == "end_turn"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7


async def test_system_prompt_is_lifted_out_of_messages() -> None:
    """Messages carries `system` at the top level; leaving it in the turns is
    rejected by the API."""
    await provider_with(messages_handler).complete(
        MODEL,
        [
            {"role": "system", "content": "you analyse repositories"},
            {"role": "user", "content": "analyse this"},
        ],
    )
    body = messages_handler.seen.read().decode()  # type: ignore[attr-defined]
    import json

    payload = json.loads(body)
    assert payload["system"] == "you analyse repositories"
    assert [m["role"] for m in payload["messages"]] == ["user"]
    assert payload["max_tokens"] > 0, "max_tokens is required by the Messages API"


async def test_required_headers_are_sent() -> None:
    await provider_with(messages_handler).complete(MODEL, [{"role": "user", "content": "x"}])
    headers = messages_handler.seen.headers  # type: ignore[attr-defined]
    assert headers["x-api-key"] == "sk-ant-test"
    assert headers["anthropic-version"] == API_VERSION


async def test_no_key_sends_no_auth_header() -> None:
    """An empty key must not become `x-api-key: `, which httpx rejects locally
    with an error far less useful than the server's own 401."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(401, json={"error": {"message": "auth"}})

    with pytest.raises(ProviderError):
        await provider_with(handler, api_key="").complete(MODEL, [{"role": "user", "content": "x"}])
    assert "x-api-key" not in captured["headers"]


async def test_rate_limit_maps_to_the_shared_category() -> None:
    """So a 429 reaches the queue's existing RATE_LIMITED backoff instead of
    being mistaken for a harness crash."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    with pytest.raises(ProviderError) as exc:
        await provider_with(handler).complete(MODEL, [{"role": "user", "content": "x"}])
    assert exc.value.category is ErrorCategory.RATE_LIMITED
    assert exc.value.retryable


async def test_api_key_never_appears_in_error_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="failed for key sk-ant-supersecret")

    with pytest.raises(ProviderError) as exc:
        await provider_with(handler).complete(MODEL, [{"role": "user", "content": "x"}])
    assert "sk-ant-supersecret" not in str(exc.value)


async def test_temperature_rejection_is_retried_without_it() -> None:
    """Claude 5 answers `temperature` with a 400. Callers pass temperature=0 to
    make analysis reproducible; which API accepts what is the provider's
    business, so it retries once rather than failing the whole analysis."""
    import json

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode())
        seen.append(payload)
        if "temperature" in payload:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "`temperature` is deprecated for this model.",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "m",
                "model": MODEL,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    result = await provider_with(handler).complete(
        MODEL, [{"role": "user", "content": "x"}], temperature=0.0
    )
    assert result.content == "ok"
    assert len(seen) == 2, "one rejected attempt, one retry"
    assert "temperature" in seen[0] and "temperature" not in seen[1]


async def test_other_400s_are_not_retried() -> None:
    """The retry is for this one deprecation, not a blanket swallow of 400s."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "max_tokens too large"}})

    with pytest.raises(ProviderError):
        await provider_with(handler).complete(
            MODEL, [{"role": "user", "content": "x"}], temperature=0.0
        )
    assert len(calls) == 1


async def test_unknown_capabilities_are_none_not_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"id": MODEL, "display_name": "Claude Sonnet 5"}]}
        )

    models = await provider_with(handler).list_models()
    assert models[0].supports_tools is None, "unknown is None, never False"
    assert models[0].context_length is None
    assert models[0].is_free is False, "Anthropic is billed; never render $0.00"
    assert models[0].display_name == "Claude Sonnet 5"
