"""OpenAI provider request shaping.

The property under test throughout: OpenAI and NIM speak the same
`/v1/chat/completions` dialect but disagree on two parameters, and the
disagreement is the vendor's, not the caller's. `suggest_setup` asks for
`max_tokens=1200, temperature=0.0` and must keep asking for exactly that —
translating it is the provider's job, so a caller can never be the reason a
repo analysis 400s.

Both facts here were measured against the live API, not inferred from docs.
"""

import json
from typing import Any

import httpx

from app.providers.nim import NimProvider
from app.providers.openai_api import OpenAIProvider

OK_BODY = {
    "model": "x",
    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
}


def capture() -> tuple[dict[str, Any], Any]:
    """Returns the dict a handler will fill with the outgoing payload."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.clear()
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    return seen, handler


async def test_openai_renames_the_token_cap_but_nim_does_not() -> None:
    """gpt-5.x answers `max_tokens` with a 400 telling you to use
    `max_completion_tokens`; NIM still expects the original name. One caller,
    two wire spellings."""
    seen, handler = capture()
    await OpenAIProvider(api_key="sk-test", transport=httpx.MockTransport(handler)).complete(
        "gpt-5.6-sol", [{"role": "user", "content": "hi"}], max_tokens=1200
    )
    assert seen["max_completion_tokens"] == 1200
    assert "max_tokens" not in seen

    seen, handler = capture()
    await NimProvider(api_key="nvapi-test", transport=httpx.MockTransport(handler)).complete(
        "openai/gpt-oss-120b", [{"role": "user", "content": "hi"}], max_tokens=1200
    )
    assert seen["max_tokens"] == 1200
    assert "max_completion_tokens" not in seen


async def test_temperature_dropped_only_for_the_families_that_reject_it() -> None:
    """gpt-5.x and the o-series fixed sampling at 1 and 400 on any explicit
    value. gpt-4.x still honours 0.0, so dropping it there would silently cost
    the determinism the analyzer asks for."""
    for model in ("gpt-5.6-sol", "gpt-5.5", "o3-mini"):
        seen, handler = capture()
        await OpenAIProvider(api_key="sk-test", transport=httpx.MockTransport(handler)).complete(
            model, [{"role": "user", "content": "hi"}], temperature=0.0
        )
        assert "temperature" not in seen, f"{model} should not receive a temperature"

    seen, handler = capture()
    await OpenAIProvider(api_key="sk-test", transport=httpx.MockTransport(handler)).complete(
        "gpt-4.1", [{"role": "user", "content": "hi"}], temperature=0.0
    )
    assert seen["temperature"] == 0.0
