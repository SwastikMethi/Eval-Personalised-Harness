import json
from typing import Any

import httpx
import pytest

from app.core.errors import ErrorCategory
from app.providers.openrouter import OpenRouterProvider, ProviderError

MODELS_PAYLOAD = {
    "data": [
        {
            "id": "qwen/qwen-2.5-coder:free",
            "name": "Qwen 2.5 Coder (free)",
            "context_length": 32768,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools", "response_format"],
        },
        {
            "id": "qwen/qwen-2.5-coder",
            "name": "Qwen 2.5 Coder",
            "context_length": 131072,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "supported_parameters": ["tools"],
        },
        {
            "id": "weird/zero-price-not-free",
            "name": "Zero price, no :free suffix",
            "context_length": 8192,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": [],
        },
        # Moving aliases: OpenRouter really does list both of these shapes.
        {
            "id": "~vendor/model-latest",
            "name": "Vendor Model (latest)",
            "context_length": 200000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "supported_parameters": ["tools"],
        },
        {
            "id": "vendor/other-latest",
            "name": "Vendor Other (latest)",
            "context_length": 200000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "supported_parameters": ["tools"],
        },
    ]
}


def provider_with(handler: Any) -> OpenRouterProvider:
    return OpenRouterProvider(api_key="sk-test", transport=httpx.MockTransport(handler))


def models_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=MODELS_PAYLOAD)


async def test_free_model_identification() -> None:
    models = await provider_with(models_handler).list_models()
    free = [m for m in models if m.is_free]
    assert [m.model_id for m in free] == ["qwen/qwen-2.5-coder:free"]
    assert free[0].supports_tools
    assert free[0].supports_structured_output


async def test_openrouter_free_banned() -> None:
    with pytest.raises(ProviderError, match="banned"):
        await provider_with(models_handler).validate_model("openrouter/free")


async def test_unknown_model_rejected() -> None:
    with pytest.raises(ProviderError, match="not available"):
        await provider_with(models_handler).validate_model("nope/nope")


async def test_moving_aliases_are_flagged() -> None:
    """`~vendor/model` and `-latest` follow the vendor's current release, so a
    rerun could measure a different model — the openrouter/free hazard again."""
    models = {m.model_id: m for m in await provider_with(models_handler).list_models()}
    assert models["~vendor/model-latest"].is_alias is True
    assert models["vendor/other-latest"].is_alias is True
    assert models["qwen/qwen-2.5-coder:free"].is_alias is False


@pytest.mark.parametrize("alias", ["~vendor/model-latest", "vendor/other-latest"])
async def test_moving_alias_cannot_be_pinned(alias: str) -> None:
    with pytest.raises(ProviderError, match="moving alias"):
        await provider_with(models_handler).validate_model(alias)


@pytest.mark.parametrize(
    ("status", "body", "category", "retryable"),
    [
        (429, "slow down", ErrorCategory.RATE_LIMITED, True),
        (402, "pay up", ErrorCategory.RATE_LIMITED, True),
        (500, "boom", ErrorCategory.MODEL_PROVIDER, True),
        (400, "maximum context length exceeded", ErrorCategory.CONTEXT_LIMIT, False),
        (400, "bad request", ErrorCategory.MODEL_PROVIDER, False),
    ],
)
async def test_error_normalization(
    status: int, body: str, category: ErrorCategory, retryable: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    provider = provider_with(handler)
    with pytest.raises(ProviderError) as exc_info:
        await provider.complete("m", [{"role": "user", "content": "x"}])
    assert exc_info.value.category is category
    assert exc_info.value.retryable is retryable


async def test_timeout_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ProviderError) as exc_info:
        await provider_with(handler).complete("m", [{"role": "user", "content": "x"}])
    assert exc_info.value.category is ErrorCategory.TIMEOUT


async def test_invalid_json_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(ProviderError) as exc_info:
        await provider_with(handler).complete("m", [{"role": "user", "content": "x"}])
    assert exc_info.value.category is ErrorCategory.MODEL_PROVIDER


async def test_usage_reported_and_routing_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining": "9"},
            json={
                "id": "gen-1",
                "model": "qwen/qwen-2.5-coder:free",
                "provider": "SomeUpstream",
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    result = await provider_with(handler).complete("m", [{"role": "user", "content": "x"}])
    assert result.usage.input_tokens == 10
    assert not result.usage.is_estimated
    assert result.raw["routed_provider"] == "SomeUpstream"
    assert result.raw["rate_limit_headers"] == {"x-ratelimit-remaining": "9"}


async def test_usage_estimated_when_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "one two three"}}]},
        )

    result = await provider_with(handler).complete(
        "m", [{"role": "user", "content": "hello world"}]
    )
    assert result.usage.is_estimated
    assert result.usage.output_tokens and result.usage.output_tokens > 0


async def test_api_key_never_in_error_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        return httpx.Response(500, text=f"server saw {auth}")

    with pytest.raises(ProviderError) as exc_info:
        await provider_with(handler).complete("m", [{"role": "user", "content": "x"}])
    assert "sk-test" not in str(exc_info.value)


async def test_request_carries_attribution_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json=MODELS_PAYLOAD)

    provider = OpenRouterProvider(
        api_key="sk-test",
        http_referer="http://localhost:3000",
        app_name="ASO",
        transport=httpx.MockTransport(handler),
    )
    await provider.list_models()
    assert seen["http-referer"] == "http://localhost:3000"
    assert seen["x-title"] == "ASO"
    assert json.loads("{}") == {}  # keep json import honest
