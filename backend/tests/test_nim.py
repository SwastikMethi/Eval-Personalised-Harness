"""NVIDIA NIM provider.

The property under test throughout: NIM's listing carries only id/owner, so
capabilities are UNKNOWN. Reporting them as False would be inventing a
capability report — spec §31, "mark unavailable metrics as null".
"""

from typing import Any

import httpx
import pytest

from app.core.errors import ErrorCategory
from app.providers.nim import NimProvider
from app.providers.openrouter import ProviderError

# Exactly what the live endpoint returns — no pricing, no context length,
# no supported_parameters.
MODELS_PAYLOAD = {
    "data": [
        {
            "id": "deepseek-ai/deepseek-coder-6.7b-instruct",
            "object": "model",
            "created": 735790403,
            "owned_by": "deepseek-ai",
        },
        {"id": "meta/llama-3.1-70b-instruct", "object": "model", "owned_by": "meta"},
        {"id": "vendor/model-latest", "object": "model", "owned_by": "vendor"},
    ]
}

CODER = "deepseek-ai/deepseek-coder-6.7b-instruct"


def provider_with(handler: Any) -> NimProvider:
    return NimProvider(api_key="nvapi-test", transport=httpx.MockTransport(handler))


def models_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=MODELS_PAYLOAD)


async def test_unknown_capabilities_are_none_not_false() -> None:
    """`supports_tools=False` would assert the model cannot use tools. We do
    not know that — NIM simply does not say."""
    models = {m.model_id: m for m in await provider_with(models_handler).list_models()}
    coder = models[CODER]
    assert coder.supports_tools is None
    assert coder.supports_structured_output is None
    assert coder.context_length is None


async def test_nim_models_are_not_presented_as_free() -> None:
    """NIM bills credits. Marking these free would show a billed run as $0.00
    the way a genuine OpenRouter `:free` model is."""
    models = await provider_with(models_handler).list_models()
    assert all(not m.is_free for m in models)
    assert all(m.provider == "nvidia" for m in models)


async def test_moving_alias_rejected_here_too() -> None:
    """The rule lives in providers/base.py precisely so a second provider
    cannot forget it."""
    with pytest.raises(ProviderError, match="moving alias"):
        await provider_with(models_handler).validate_model("vendor/model-latest")


async def test_unknown_model_rejected() -> None:
    with pytest.raises(ProviderError, match="not available"):
        await provider_with(models_handler).validate_model("nope/nope")


async def test_rate_limit_maps_to_the_shared_category() -> None:
    """A 429 must reach the queue's RATE_LIMITED backoff, not read as a crash."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="too many requests")

    with pytest.raises(ProviderError) as exc:
        await provider_with(handler).complete(CODER, [{"role": "user", "content": "hi"}])
    assert exc.value.category is ErrorCategory.RATE_LIMITED
    assert exc.value.retryable


async def test_tools_reach_the_payload_and_tool_calls_come_back() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": CODER,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {"id": "c1", "function": {"name": "edit", "arguments": "{}"}}
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    tools = [{"type": "function", "function": {"name": "edit"}}]
    result = await provider_with(handler).complete(
        CODER, [{"role": "user", "content": "go"}], tools=tools, tool_choice="auto"
    )

    assert seen["tools"] == tools
    assert seen["tool_choice"] == "auto"
    assert result.finish_reason == "tool_calls"
    assert result.message is not None
    assert result.message["tool_calls"][0]["function"]["name"] == "edit"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 3)


async def test_missing_usage_is_none_not_zero() -> None:
    """Absent usage is unknown. Zero would be a fabricated measurement."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": CODER,
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            },
        )

    result = await provider_with(handler).complete(CODER, [{"role": "user", "content": "x"}])
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


async def test_api_key_never_appears_in_error_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="failed for Bearer nvapi-supersecret")

    with pytest.raises(ProviderError) as exc:
        await provider_with(handler).complete(CODER, [{"role": "user", "content": "x"}])
    assert "nvapi-supersecret" not in str(exc.value)


async def test_two_providers_route_independently() -> None:
    """A NIM run and an OpenRouter run in the same experiment must each reach
    their own provider — the reason runs carry a provider at all."""
    from app.api import proxy
    from app.providers.fake import FakeProvider

    nim = provider_with(models_handler)
    proxy.set_provider(FakeProvider())  # default
    proxy.register_provider(nim)
    try:
        assert proxy.provider_for("nvidia") is nim
        assert proxy.provider_for("fake").name == "fake"
        # Unknown names fall back to the default rather than exploding.
        assert proxy.provider_for("nope").name == "fake"
    finally:
        proxy.set_provider(FakeProvider())
