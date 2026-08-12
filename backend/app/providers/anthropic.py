"""Anthropic provider (spec §4).

Not built on OpenAICompatibleProvider, because the Messages API differs in
every part that matters:

  auth      x-api-key + anthropic-version, not Bearer
  system    a top-level field, not a message with role="system"
  body      max_tokens is REQUIRED
  response  content: [{type: "text", text: ...}], not choices[0].message
  usage     input_tokens / output_tokens, not prompt_/completion_tokens

Folding that into the shared client as conditionals would make both harder to
read than keeping them apart. The adapter's job is to normalise all of it into
CompletionResult so nothing downstream learns a second shape.

Model listing: the Messages API has a /v1/models endpoint, but it needs auth —
unlike NIM, keyless browsing is not possible, so list_models surfaces the
server's own 401 rather than pretending.
"""

import json
import time
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

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
# Messages requires max_tokens. Analysis answers are JSON decisions, not prose,
# so this is a ceiling rather than a target.
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Same rule as the other providers: an empty key must not become an
        # illegal header value that httpx rejects locally with an opaque error.
        self._headers = (
            {"x-api-key": api_key, "anthropic-version": API_VERSION} if api_key else {}
        )
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
            display_name=entry.get("display_name") or model_id,
            # The listing carries id/display_name/created_at only. Unknown is
            # None, never False (spec §31) — and never fabricated as a number.
            context_length=None,
            supports_tools=None,
            supports_structured_output=None,
            input_price_per_token=0.0,
            output_price_per_token=0.0,
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
        start = time.monotonic()
        async with self._client() as client:
            resp = await client.get(f"{self._base_url}/models")
        return {
            "ok": resp.status_code == 200,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    @staticmethod
    def _split_system(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        """Messages carries `system` at the top level, not as a turn."""
        system = "\n\n".join(
            str(m.get("content") or "") for m in messages if m.get("role") == "system"
        )
        rest = [m for m in messages if m.get("role") != "system"]
        return (system or None), rest

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        system, turns = self._split_system(messages)
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": turns,
            "max_tokens": kwargs.get("max_tokens") or DEFAULT_MAX_TOKENS,
        }
        if system:
            payload["system"] = system
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]

        try:
            async with self._client() as client:
                resp = await client.post(f"{self._base_url}/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "provider request timed out", ErrorCategory.TIMEOUT, retryable=True
            ) from exc
        if resp.status_code != 200:
            # Shared normalization keeps 429 on the queue's RATE_LIMITED path.
            raise normalize_http_error(resp.status_code, resp.text)
        try:
            body = resp.json()
            blocks = body["content"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderError(
                "invalid completion response", ErrorCategory.MODEL_PROVIDER, retryable=True
            ) from exc

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage_raw = body.get("usage") or {}
        usage = CompletionUsage(
            input_tokens=usage_raw.get("input_tokens"),
            output_tokens=usage_raw.get("output_tokens"),
            cached_tokens=usage_raw.get("cache_read_input_tokens"),
        )
        return CompletionResult(
            content=text,
            usage=usage,
            # Normalised to the OpenAI message shape so callers stay uniform.
            message={"role": "assistant", "content": text},
            finish_reason=body.get("stop_reason"),
            raw={"routed_model": body.get("model"), "id": body.get("id")},
        )
