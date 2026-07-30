"""Run-scoped model proxy (spec §12).

Skeleton version: validates the per-run bearer token, enforces the pinned
model, and forwards to the configured provider (FakeProvider in Stage 1;
OpenRouter lands in Stage 3 behind the same interface). Sandbox harnesses
never see a real API key — only this endpoint plus a run token.
"""

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.providers.base import ModelProvider
from app.providers.fake import FakeProvider

log = logging.getLogger(__name__)
router = APIRouter()

# run_id -> {"token": str, "model_id": str, "requests": int, "max_requests": int}
_active_tokens: dict[str, dict[str, Any]] = {}
_provider: ModelProvider = FakeProvider()


def set_provider(provider: ModelProvider) -> None:
    global _provider
    _provider = provider


def issue_run_token(run_id: str, model_id: str, max_requests: int = 50) -> str:
    token = secrets.token_urlsafe(24)
    _active_tokens[run_id] = {
        "token": token,
        "model_id": model_id,
        "requests": 0,
        "max_requests": max_requests,
    }
    return token


def revoke_run_token(run_id: str) -> None:
    _active_tokens.pop(run_id, None)


def _authorize(authorization: str, model_id: str) -> dict[str, Any]:
    token = authorization.removeprefix("Bearer ").strip()
    for run_id, entry in _active_tokens.items():
        if secrets.compare_digest(entry["token"], token):
            if entry["model_id"] != model_id:
                raise HTTPException(403, "model not pinned for this run")
            if entry["requests"] >= entry["max_requests"]:
                raise HTTPException(429, "run request budget exceeded")
            entry["requests"] += 1
            entry["run_id"] = run_id
            return entry
    raise HTTPException(401, "invalid or expired run token")


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatRequest, authorization: str = Header(default="")
) -> dict[str, Any]:
    entry = _authorize(authorization, body.model)
    result = await _provider.complete(body.model, body.messages)
    log.info(
        "proxy completion",
        extra={
            "run_id": entry.get("run_id"),
            "model_id": body.model,
            "event_type": "model_request",
        },
    )
    return {
        "id": "proxy-cmpl",
        "object": "chat.completion",
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.usage.input_tokens,
            "completion_tokens": result.usage.output_tokens,
        },
    }
