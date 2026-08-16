from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


def is_moving_alias(model_id: str) -> bool:
    """True for ids that do not name one fixed model.

    `~vendor/model` and `vendor/model-latest` follow a vendor's current
    release, so pinning one means a rerun can silently measure a different
    model — the reason `openrouter/free` is banned (spec §4: never silently
    replace a selected model). Lives here rather than in one provider so the
    next provider cannot forget the rule.
    """
    return model_id.startswith("~") or model_id.endswith("-latest")


@dataclass
class ModelInfo:
    provider: str
    model_id: str
    display_name: str
    context_length: int | None
    # None means UNKNOWN, not unsupported. OpenRouter publishes
    # `supported_parameters`; NVIDIA NIM's listing carries only id/owner, so
    # claiming False there would be inventing a capability report (spec §31:
    # mark unavailable metrics as null). Preflight (§21) is what resolves it.
    supports_tools: bool | None
    supports_structured_output: bool | None
    input_price_per_token: float
    output_price_per_token: float
    is_free: bool
    availability_status: str
    # A moving alias (`~vendor/model`, `vendor/model-latest`) resolves to
    # whatever is current, so the underlying model can change between runs.
    # That is the same hazard `openrouter/free` is banned for — it destroys a
    # controlled comparison — so aliases are never pinnable.
    is_alias: bool = False


@dataclass
class CompletionUsage:
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    is_estimated: bool = False


@dataclass
class CompletionResult:
    content: str
    usage: CompletionUsage
    raw: dict[str, Any]
    # The provider's assistant message verbatim, including `tool_calls`, and
    # the real finish_reason. Harnesses that use function calling are broken by
    # anything that rebuilds the message from `content` alone, so the proxy
    # forwards these untouched. None means the provider returned neither.
    message: dict[str, Any] | None = None
    finish_reason: str | None = None


class ModelProvider(ABC):
    name: str

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def validate_model(self, model_id: str) -> ModelInfo: ...

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]: ...

    @abstractmethod
    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult: ...
