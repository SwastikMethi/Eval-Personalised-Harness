"""Run-scoped model proxy (spec §12, hardened per eng review T9).

Sandbox harnesses never see a real API key — only this endpoint plus a
short-lived per-run token. The proxy enforces: pinned model, request budget,
token budgets, spend ceiling, token expiry (renewable), and records a
ModelRequestMetric per request. Secrets are never logged or echoed.
"""

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.errors import ErrorCategory
from app.db.engine import SessionLocal
from app.models import ModelRequestMetric
from app.providers.base import ModelProvider
from app.providers.fake import FakeProvider
from app.providers.openrouter import ProviderError

log = logging.getLogger(__name__)
router = APIRouter()

TOKEN_TTL_S = 2 * 60 * 60


@dataclass
class RunToken:
    run_id: str
    token: str
    model_id: str
    expires_at: float
    max_requests: int = 50
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_usd: float | None = None
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    input_price: float = 0.0
    output_price: float = 0.0
    rate_limited: bool = False
    # Which provider serves THIS run. A run declares its provider in its
    # combination, so a fake combination stays on the fake provider even when a
    # real OpenRouter key is configured — otherwise the zero-cost path becomes
    # unusable the moment a key exists.
    provider: str = "openrouter"
    extra: dict[str, Any] = field(default_factory=dict)


_active_tokens: dict[str, RunToken] = {}
_provider: ModelProvider = FakeProvider()
_named_providers: dict[str, ModelProvider] = {"fake": FakeProvider()}


def set_provider(provider: ModelProvider) -> None:
    """Set the default provider, and register it under its own name."""
    global _provider
    _provider = provider
    _named_providers[provider.name] = provider


def register_provider(provider: ModelProvider) -> None:
    """Make a provider routable by name without making it the default.

    Runs carry their own provider, so several can be live at once and a single
    experiment can compare the same model across two of them.
    """
    _named_providers[provider.name] = provider


def provider_for(name: str) -> ModelProvider:
    return _named_providers.get(name, _provider)


def issue_run_token(
    run_id: str,
    model_id: str,
    max_requests: int = 50,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_cost_usd: float | None = None,
    input_price: float = 0.0,
    output_price: float = 0.0,
    provider: str = "openrouter",
) -> str:
    token = secrets.token_urlsafe(24)
    _active_tokens[run_id] = RunToken(
        run_id=run_id,
        token=token,
        model_id=model_id,
        expires_at=time.time() + TOKEN_TTL_S,
        max_requests=max_requests,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_cost_usd=max_cost_usd,
        input_price=input_price,
        output_price=output_price,
        provider=provider,
    )
    return token


def renew_run_token(run_id: str) -> None:
    """Extend expiry for long or rate-limited runs (eng review Tension 5)."""
    entry = _active_tokens.get(run_id)
    if entry is not None:
        entry.expires_at = time.time() + TOKEN_TTL_S


def run_usage(run_id: str) -> dict[str, Any]:
    """Observed usage for a run. Read before `revoke_run_token` clears it."""
    entry = _active_tokens.get(run_id)
    if entry is None:
        return {}
    return {
        "requests": entry.requests,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cost_usd": round(entry.cost_usd, 6),
        "rate_limited": entry.rate_limited,
        "budget_exhausted": entry.requests >= entry.max_requests,
    }


def revoke_run_token(run_id: str) -> None:
    _active_tokens.pop(run_id, None)


def _authorize(authorization: str, model_id: str) -> RunToken:
    token = authorization.removeprefix("Bearer ").strip()
    for entry in _active_tokens.values():
        if secrets.compare_digest(entry.token, token):
            if time.time() > entry.expires_at:
                raise HTTPException(401, "run token expired")
            if entry.model_id != model_id:
                raise HTTPException(403, "model not pinned for this run")
            if entry.requests >= entry.max_requests:
                raise HTTPException(429, "run request budget exceeded")
            if entry.max_input_tokens and entry.input_tokens >= entry.max_input_tokens:
                raise HTTPException(429, "run input-token budget exceeded")
            if entry.max_output_tokens and entry.output_tokens >= entry.max_output_tokens:
                raise HTTPException(429, "run output-token budget exceeded")
            if entry.max_cost_usd and entry.cost_usd >= entry.max_cost_usd:
                raise HTTPException(429, "run spend ceiling exceeded")
            entry.requests += 1
            return entry
    raise HTTPException(401, "invalid or expired run token")


def _record_metric(
    entry: RunToken, latency_ms: int, usage: Any, status: int, raw: dict[str, Any]
) -> None:
    try:
        with SessionLocal() as session:
            session.add(
                ModelRequestMetric(
                    run_id=entry.run_id,
                    model_id=entry.model_id,
                    latency_ms=latency_ms,
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    is_estimated=getattr(usage, "is_estimated", False),
                    http_status=status,
                    raw_meta=raw,
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 - metrics must never break the request path
        log.warning("failed to persist model request metric", extra={"run_id": entry.run_id})


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None
    # Function calling: dropping these silently turns a tool-using harness into
    # a plain chat client that never edits anything (spec §21 compatibility).
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    response_format: dict[str, Any] | None = None


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatRequest, authorization: str = Header(default="")
) -> dict[str, Any]:
    entry = _authorize(authorization, body.model)
    start = time.monotonic()
    try:
        result = await provider_for(entry.provider).complete(
            body.model,
            body.messages,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            tools=body.tools,
            tool_choice=body.tool_choice,
            response_format=body.response_format,
        )
    except ProviderError as exc:
        latency = int((time.monotonic() - start) * 1000)
        _record_metric(entry, latency, None, exc.status or 502, {"error": str(exc)})
        if exc.category is ErrorCategory.RATE_LIMITED:
            # Remembered on the run token so the orchestrator can distinguish
            # "provider throttled us" from "the harness broke" after the fact,
            # without parsing harness error strings.
            entry.rate_limited = True
            raise HTTPException(429, f"provider error [{exc.category}]: {exc}") from exc
        raise HTTPException(502, f"provider error [{exc.category}]: {exc}") from exc
    latency = int((time.monotonic() - start) * 1000)

    if result.usage.input_tokens:
        entry.input_tokens += result.usage.input_tokens
        entry.cost_usd += result.usage.input_tokens * entry.input_price
    if result.usage.output_tokens:
        entry.output_tokens += result.usage.output_tokens
        entry.cost_usd += result.usage.output_tokens * entry.output_price

    _record_metric(entry, latency, result.usage, 200, result.raw)
    log.info(
        "proxy completion",
        extra={
            "run_id": entry.run_id,
            "model_id": body.model,
            "event_type": "model_request",
            "duration": latency,
        },
    )
    # Forward the provider's own message rather than rebuilding it: a
    # hand-built {"role","content"} drops tool_calls and forces finish_reason
    # to "stop", which makes function-calling harnesses believe the model
    # answered when it actually asked to call a tool.
    message = result.message or {"role": "assistant", "content": result.content}
    return {
        "id": "proxy-cmpl",
        "object": "chat.completion",
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": result.finish_reason or "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.usage.input_tokens,
            "completion_tokens": result.usage.output_tokens,
        },
    }
