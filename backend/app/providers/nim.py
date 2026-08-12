"""NVIDIA NIM provider (spec §4: "any OpenAI-compatible endpoint").

Exists because the OpenRouter free tier — roughly 50 requests a day without
credits — has been the binding constraint on every real run in this project.
A second provider is headroom, not a replacement: OpenRouter stays, and the
provider is chosen per combination.

What NIM does NOT tell us matters as much as what it does. Its listing carries
only id/object/created/owned_by:

    {"id": "01-ai/yi-large", "object": "model", "created": ..., "owned_by": ...}

No pricing, no context length, no `supported_parameters`. So context length and
tool support are reported as **None — unknown, not unsupported** (spec §31:
mark unavailable metrics as null). Preflight (§21) is what would settle them
empirically. Claiming `supports_tools=False` here would be inventing a
capability report, which is worse than admitting ignorance.

Cost: NIM bills credits, not per-token dollars we can read, so prices stay 0.0
and `is_free` stays False. A NIM run must not display "$0.00" the way a
genuine OpenRouter `:free` model does.
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

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NimProvider(ModelProvider):
    name = "nvidia"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Only send the header when there is a key: `Bearer ` is an illegal
        # header value and httpx rejects it client-side with a protocol error,
        # which is far less useful than the server's own 401. Listing models
        # needs no auth at all, so keyless browsing still works.
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            headers=self._headers,
            timeout=settings.provider_timeout_seconds,
        )

    @staticmethod
    def _model_info(entry: dict[str, Any]) -> ModelInfo:
        model_id = entry.get("id", "")
        return ModelInfo(
            provider="nvidia",
            model_id=model_id,
            display_name=model_id,
            # Every one of these is genuinely unknown from NIM's listing.
            context_length=None,
            supports_tools=None,
            supports_structured_output=None,
            input_price_per_token=0.0,
            output_price_per_token=0.0,
            # Credits, not a free per-token tier. Saying True would present a
            # billed model as free.
            is_free=False,
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
        # Same passthrough as OpenRouter: dropping these silently degrades a
        # function-calling harness into plain chat.
        for key in ("temperature", "max_tokens", "tools", "tool_choice", "response_format"):
            if kwargs.get(key) is not None:
                payload[key] = kwargs[key]
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

        content = message.get("content") or ""
        usage_raw = body.get("usage") or {}
        # Never fabricate usage: absent means None, not zero.
        usage = CompletionUsage(
            input_tokens=usage_raw.get("prompt_tokens"),
            output_tokens=usage_raw.get("completion_tokens"),
            cached_tokens=None,
        )
        return CompletionResult(
            content=content,
            usage=usage,
            message=message,
            finish_reason=choice.get("finish_reason"),
            raw={"routed_model": body.get("model"), "id": body.get("id")},
        )
