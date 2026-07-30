"""OpenRouter provider (spec §4).

Rules enforced here: never `openrouter/free` (it routes to arbitrary models);
free variants identified by pricing metadata AND `:free` suffix; returned
routing metadata recorded for reproducibility; usage estimated (and flagged)
only when the provider omits it.
"""

import json
import re
from typing import Any

import httpx

from app.core.errors import ErrorCategory
from app.providers.base import CompletionResult, CompletionUsage, ModelInfo, ModelProvider


class ProviderError(Exception):
    def __init__(
        self, message: str, category: ErrorCategory, retryable: bool, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status = status


def _redact(text: str) -> str:
    return re.sub(r"(Bearer\s+)\S+|sk-[A-Za-z0-9_-]+", "***", text)[:500]


def normalize_http_error(status: int, body_snippet: str) -> ProviderError:
    snippet = _redact(body_snippet)
    if status in (402, 429):
        return ProviderError(
            f"rate limited ({status}): {snippet}", ErrorCategory.RATE_LIMITED, retryable=True,
            status=status,
        )
    if status == 400 and "context" in body_snippet.lower():
        return ProviderError(
            f"context limit: {snippet}", ErrorCategory.CONTEXT_LIMIT, retryable=False,
            status=status,
        )
    if status >= 500:
        return ProviderError(
            f"provider error ({status}): {snippet}", ErrorCategory.MODEL_PROVIDER,
            retryable=True, status=status,
        )
    return ProviderError(
        f"provider rejected request ({status}): {snippet}", ErrorCategory.MODEL_PROVIDER,
        retryable=False, status=status,
    )


def _estimate_tokens(messages: list[dict[str, Any]], content: str) -> CompletionUsage:
    prompt = sum(len(str(m.get("content", "")).split()) for m in messages)
    return CompletionUsage(
        input_tokens=int(prompt * 1.3),
        output_tokens=int(len(content.split()) * 1.3),
        cached_tokens=None,
        is_estimated=True,
    )


class OpenRouterProvider(ModelProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        http_referer: str = "",
        app_name: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": http_referer,
            "X-Title": app_name,
        }
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport, headers=self._headers, timeout=120
        )

    @staticmethod
    def _model_info(entry: dict[str, Any]) -> ModelInfo:
        pricing = entry.get("pricing", {})
        in_price = float(pricing.get("prompt", 0) or 0)
        out_price = float(pricing.get("completion", 0) or 0)
        model_id = entry.get("id", "")
        params = entry.get("supported_parameters") or []
        return ModelInfo(
            provider="openrouter",
            model_id=model_id,
            display_name=entry.get("name", model_id),
            context_length=entry.get("context_length"),
            supports_tools="tools" in params,
            supports_structured_output="structured_outputs" in params
            or "response_format" in params,
            input_price_per_token=in_price,
            output_price_per_token=out_price,
            is_free=(in_price == 0 and out_price == 0) and model_id.endswith(":free"),
            availability_status="available",
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
        if model_id == "openrouter/free":
            raise ProviderError(
                "openrouter/free routes to arbitrary models and is banned for experiments",
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
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"ok": resp.status_code == 200, "latency_ms": latency_ms}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        payload: dict[str, Any] = {"model": model_id, "messages": messages}
        for key in ("temperature", "max_tokens"):
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
            raise normalize_http_error(resp.status_code, resp.text)
        try:
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise ProviderError(
                "invalid completion response", ErrorCategory.MODEL_PROVIDER, retryable=True
            ) from exc
        usage_raw = body.get("usage") or {}
        if usage_raw.get("prompt_tokens") is not None:
            usage = CompletionUsage(
                input_tokens=usage_raw.get("prompt_tokens"),
                output_tokens=usage_raw.get("completion_tokens"),
                cached_tokens=(usage_raw.get("prompt_tokens_details") or {}).get("cached_tokens"),
            )
        else:
            usage = _estimate_tokens(messages, content)
        rate_headers = {
            k: v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit")
        }
        return CompletionResult(
            content=content,
            usage=usage,
            raw={
                # Reproducibility: which upstream actually served this request.
                "routed_model": body.get("model"),
                "routed_provider": body.get("provider"),
                "rate_limit_headers": rate_headers,
                "id": body.get("id"),
            },
        )
