"""Run-scoped model proxy (spec §12, hardened per eng review T9).

Sandbox harnesses never see a real API key — only this endpoint plus a
short-lived per-run token. The proxy enforces: pinned model, request budget,
token budgets, spend ceiling, token expiry (renewable), and records a
ModelRequestMetric per request. Secrets are never logged or echoed.
"""

import asyncio
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
    # None means uncapped: let the agent stop when it is finished rather than
    # when it runs out of allowance. The wall-clock timeout is then the backstop,
    # and `max_input_tokens` below is what actually bounds spend — a request
    # count does not, since 100 calls cost anywhere from 100k to 3M tokens
    # depending on how much history the harness resends.
    max_requests: int | None = 50
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
    # A retryable upstream failure (5xx) as opposed to a rejected request.
    # Recorded for the same reason as rate_limited: the orchestrator must be
    # able to tell "the provider blew up" from "the harness broke" without
    # parsing harness error strings, and a 504 from a slow model is not a
    # harness bug.
    provider_error: bool = False
    provider_error_detail: str = ""
    # False for a rejection that will never succeed (404 model not enabled for
    # the account, 400 bad request). Retrying those costs a container build to
    # be told the same thing again.
    provider_error_retryable: bool = True
    # Every call that left this process, including the ones that returned
    # nothing. `requests` counts only usable answers, so the difference is
    # where provider flakiness shows up instead of being hidden by the refund.
    attempted: int = 0
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
    max_requests: int | None = 50,
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
        "provider_error": entry.provider_error,
        "provider_error_retryable": entry.provider_error_retryable,
        "provider_error_detail": entry.provider_error_detail,
        # Attempts include calls that returned nothing; `requests` does not.
        # Both are reported so a refund never hides provider flakiness.
        "attempted": entry.attempted,
        "budget_exhausted": (
            entry.max_requests is not None and entry.requests >= entry.max_requests
        )
        or bool(entry.max_input_tokens and entry.input_tokens >= entry.max_input_tokens),
    }


def revoke_run_token(run_id: str) -> None:
    _active_tokens.pop(run_id, None)


# A run's budget ending and a provider throttling us both arrive as 429, and a
# harness cannot tell them apart: it backs off and retries, so a run that had
# simply spent its allowance held a container until the 1800s timeout and was
# then recorded as a TIMEOUT. Efficiency is 15% of the score, so an orderly
# stop must not be scored as slowness.
#
# The status stays 429 because harnesses already understand it; the marker is
# what says "never, for this run" rather than "later".
TERMINAL_HEADER = "X-ASO-Terminal"
BUDGET_EXHAUSTED = "budget_exhausted"


def _budget_exhausted(detail: str) -> HTTPException:
    return HTTPException(
        429,
        f"{detail} — terminal for this run, do not retry",
        headers={TERMINAL_HEADER: BUDGET_EXHAUSTED},
    )


def _authorize(authorization: str, model_id: str) -> RunToken:
    token = authorization.removeprefix("Bearer ").strip()
    for entry in _active_tokens.values():
        if secrets.compare_digest(entry.token, token):
            if time.time() > entry.expires_at:
                raise HTTPException(401, "run token expired")
            if entry.model_id != model_id:
                raise HTTPException(403, "model not pinned for this run")
            if entry.max_requests is not None and entry.requests >= entry.max_requests:
                raise _budget_exhausted("run request budget exceeded")
            if entry.max_input_tokens and entry.input_tokens >= entry.max_input_tokens:
                raise _budget_exhausted("run input-token budget exceeded")
            if entry.max_output_tokens and entry.output_tokens >= entry.max_output_tokens:
                raise _budget_exhausted("run output-token budget exceeded")
            if entry.max_cost_usd and entry.cost_usd >= entry.max_cost_usd:
                raise _budget_exhausted("run spend ceiling exceeded")
            entry.requests += 1
            entry.attempted += 1
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


# A harness has no retry of its own: one 5xx anywhere in a twenty-step run ends
# the run. Measured against nvidia/nemotron-3-ultra-550b-a55b, which returns a
# sub-second 503 for roughly one request in seven — reproduced with a plain
# direct call, so it is the provider's, not ours. At that rate an unretried run
# has almost no chance of finishing, and the result would be recorded against
# the harness rather than the provider.
#
# Only errors the provider itself marked retryable. Rate limiting is excluded
# on purpose: it keeps its own 429 path so the queue can back off, and retrying
# inline would spend quota fighting a limit that needs waiting out.
PROVIDER_RETRY_ATTEMPTS = 2
PROVIDER_RETRY_BACKOFF_S = (1.0, 3.0)


def _retryable(exc: ProviderError) -> bool:
    return exc.retryable and exc.category in (
        ErrorCategory.MODEL_PROVIDER,
        ErrorCategory.TIMEOUT,
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatRequest, authorization: str = Header(default="")
) -> dict[str, Any]:
    entry = _authorize(authorization, body.model)
    for attempt in range(PROVIDER_RETRY_ATTEMPTS + 1):
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
            break
        except ProviderError as exc:
            latency = int((time.monotonic() - start) * 1000)
            # Written for every attempt, including ones a retry goes on to
            # recover. Hiding the failures would understate exactly the
            # provider flakiness this product is supposed to measure.
            _record_metric(entry, latency, None, exc.status or 502, {"error": str(exc)})
            if _retryable(exc) and attempt < PROVIDER_RETRY_ATTEMPTS:
                log.warning(
                    "proxy retrying provider error",
                    extra={
                        "run_id": entry.run_id,
                        "model_id": body.model,
                        "event_type": "model_request_retry",
                        "attempt": attempt + 1,
                    },
                )
                await asyncio.sleep(PROVIDER_RETRY_BACKOFF_S[attempt])
                continue
            # Refund the request: the agent got nothing it could use, and
            # charging for it means a model behind a flaky gateway is given
            # fewer steps than one on a healthy provider — our infrastructure
            # changing the measurement. Measured: deepseek-v4 lost 2 of 8 steps
            # to 504s. The refund is bounded elsewhere and cannot become free
            # spend: the metric rows above are already written and the spend and
            # token ceilings are untouched. It happens only once, here on the
            # give-up path, so a call that a retry rescues still counts as the
            # one request the agent actually made.
            entry.requests = max(0, entry.requests - 1)
            if exc.category is ErrorCategory.RATE_LIMITED:
                # Remembered on the run token so the orchestrator can distinguish
                # "provider throttled us" from "the harness broke" after the fact,
                # without parsing harness error strings.
                entry.rate_limited = True
                raise HTTPException(429, f"provider error [{exc.category}]: {exc}") from exc
            if exc.category is ErrorCategory.MODEL_PROVIDER:
                # Every provider rejection, not only the retryable ones. A 404
                # ("model not enabled for this account") carried no marker at all,
                # so it fell through to HARNESS — booking the provider's refusal
                # against whichever harness happened to be running, in the very
                # statistic this product exists to produce.
                entry.provider_error = True
                entry.provider_error_retryable = exc.retryable
                entry.provider_error_detail = f"{exc.status or 502} after {latency}ms"
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
