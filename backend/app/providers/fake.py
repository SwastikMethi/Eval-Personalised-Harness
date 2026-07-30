"""Deterministic in-process provider for tests and `make demo` (spec §24)."""

from typing import Any

from app.providers.base import CompletionResult, CompletionUsage, ModelInfo, ModelProvider

FAKE_MODEL = ModelInfo(
    provider="fake",
    model_id="fake/deterministic-1:free",
    display_name="Fake Deterministic 1 (free)",
    context_length=32768,
    supports_tools=True,
    supports_structured_output=True,
    input_price_per_token=0.0,
    output_price_per_token=0.0,
    is_free=True,
    availability_status="available",
)


class FakeProvider(ModelProvider):
    name = "fake"

    async def list_models(self) -> list[ModelInfo]:
        return [FAKE_MODEL]

    async def validate_model(self, model_id: str) -> ModelInfo:
        if model_id != FAKE_MODEL.model_id:
            raise ValueError(f"unknown model: {model_id}")
        return FAKE_MODEL

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        await self.validate_model(model_id)
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        content = f"FAKE_COMPLETION for: {str(last_user)[:80]}"
        prompt_tokens = sum(len(str(m.get("content", "")).split()) for m in messages)
        return CompletionResult(
            content=content,
            usage=CompletionUsage(
                input_tokens=prompt_tokens, output_tokens=len(content.split()), cached_tokens=0
            ),
            raw={"model": model_id, "deterministic": True},
        )
