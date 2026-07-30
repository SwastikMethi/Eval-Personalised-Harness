from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ModelInfo:
    provider: str
    model_id: str
    display_name: str
    context_length: int | None
    supports_tools: bool
    supports_structured_output: bool
    input_price_per_token: float
    output_price_per_token: float
    is_free: bool
    availability_status: str


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
