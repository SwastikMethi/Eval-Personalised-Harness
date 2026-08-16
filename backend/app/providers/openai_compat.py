"""Shared client for OpenAI-compatible endpoints (spec §4).

NIM, OpenAI and anything else speaking `/v1/chat/completions` differ only in
base URL, display name, and what their listing endpoint is willing to tell us.
That is not enough difference to justify a second copy of the request/response
handling — a duplicated provider is a place for one copy to get a fix the other
does not.

Anthropic is deliberately NOT built on this: its Messages API has a different
request shape, a different response shape and different auth, so it gets its own
adapter rather than a pile of conditionals here.
"""

import json
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ErrorCategory
from app.providers.base import (
    CompletionResult,
    CompletionUsage,
    ModelInfo,
    ModelProvider,
    is_moving_alias,
)
from app.providers.openrouter import ProviderError, normalize_http_error


class OpenAICompatibleProvider(ModelProvider):
    """Subclasses set `name` and `default_base_url`; everything else is shared."""

    name = "openai-compatible"
    default_base_url = ""
    # True only for a provider whose listing genuinely marks models as free to
    # call. Credit-billed providers must not render as "$0.00".
    is_free_tier = False
    # What this vendor calls the output-token cap on the wire. OpenAI's gpt-5
    # family rejects `max_tokens` outright ("Unsupported parameter ... Use
    # 'max_completion_tokens' instead") while NIM still expects the original
    # name, so it is a per-vendor spelling rather than a caller's concern.
    max_tokens_field = "max_tokens"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.default_base_url).rstrip("/")
        # Only send the header when there is a key: `Bearer ` is an illegal
        # header value and httpx rejects it client-side with a protocol error,
        # which is far less useful than the server's own 401.
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            headers=self._headers,
            timeout=settings.provider_timeout_seconds,
        )

    def _model_info(self, entry: dict[str, Any]) -> ModelInfo:
        model_id = entry.get("id", "")
        return ModelInfo(
            provider=self.name,
            model_id=model_id,
            display_name=model_id,
            # An OpenAI-style listing carries none of these. None means
            # UNKNOWN, not unsupported — claiming False would invent a
            # capability report (spec §31).
            context_length=None,
            supports_tools=None,
            supports_structured_output=None,
            input_price_per_token=0.0,
            output_price_per_token=0.0,
            is_free=self.is_free_tier,
            availability_status="available",
            is_alias=is_moving_alias(model_id),
        )

    async def list_models(self) -> list[ModelInfo]:
        async with self._client() as client:
            resp = await client.get(f"{self._base_url}/models")
        if resp.status_code != 200:
            raise normalize_http_error(resp.status_code, resp.text)
        try:
            data = resp.json()["data"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderError(
                "invalid /models response", ErrorCategory.MODEL_PROVIDER, retryable=True
            ) from exc
        return [self._model_info(e) for e in data]

    async def validate_model(self, model_id: str) -> ModelInfo:
        if is_moving_alias(model_id):
            raise ProviderError(
                f"{model_id} is a moving alias — it follows the vendor's current release, so a "
                "rerun could measure a different model. Pin the exact versioned id instead.",
                ErrorCategory.MODEL_PROVIDER,
                retryable=False,
            )
        models = {m.model_id: m for m in await self.list_models()}
        if model_id not in models:
            raise ProviderError(
                f"model not available: {model_id}", ErrorCategory.MODEL_PROVIDER, retryable=False
            )
        return models[model_id]

    async def test_connection(self) -> dict[str, Any]:
        import time

        start = time.monotonic()
        async with self._client() as client:
            resp = await client.get(f"{self._base_url}/models")
        return {
            "ok": resp.status_code == 200,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        payload: dict[str, Any] = {"model": model_id, "messages": messages}
        # Dropping these silently degrades a function-calling harness into
        # plain chat.
        for key in ("temperature", "max_tokens", "tools", "tool_choice", "response_format"):
            if kwargs.get(key) is not None:
                payload[self.max_tokens_field if key == "max_tokens" else key] = kwargs[key]
        try:
            async with self._client() as client:
                resp = await client.post(f"{self._base_url}/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "provider request timed out", ErrorCategory.TIMEOUT, retryable=True
            ) from exc
        if resp.status_code != 200:
            # Shared normalization, so a 429 still reaches the queue's
            # RATE_LIMITED backoff rather than being mistaken for a crash.
            raise normalize_http_error(resp.status_code, resp.text)
        try:
            body = resp.json()
            choice = body["choices"][0]
            message = choice["message"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise ProviderError(
                "invalid completion response", ErrorCategory.MODEL_PROVIDER, retryable=True
            ) from exc

        usage_raw = body.get("usage") or {}
        # Never fabricate usage: absent means None, not zero.
        usage = CompletionUsage(
            input_tokens=usage_raw.get("prompt_tokens"),
            output_tokens=usage_raw.get("completion_tokens"),
            cached_tokens=None,
        )
        return CompletionResult(
            content=message.get("content") or "",
            usage=usage,
            message=message,
            finish_reason=choice.get("finish_reason"),
            raw={"routed_model": body.get("model"), "id": body.get("id")},
        )
