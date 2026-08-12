"""Harness adapter contract (spec §3). All harnesses normalize to HarnessRunResult."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HarnessRunRequest:
    task_id: str
    task_prompt: str
    workspace_path: Path
    model_id: str
    provider: str
    timeout_seconds: int
    max_steps: int
    temperature: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # Injected by the orchestrator: how the harness reaches the model proxy.
    proxy_base_url: str = ""
    run_token: str = ""


@dataclass
class HarnessRunResult:
    status: str  # completed | failed | timeout | cancelled
    final_message: str | None
    patch: str | None
    started_at: str
    completed_at: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    # None where the harness could not report it — an unreadable trajectory is
    # an absent measurement, not a measured zero.
    model_requests: int | None
    agent_steps: int | None
    tool_calls: int
    # None where the harness has no such concept — a CodeAgent runs Python, not
    # shell commands. Reporting 0 would read as "executed nothing", which is a
    # measurement it never made (§4: mark unavailable metrics null).
    commands_executed: int | None
    error_type: str | None
    error_message: str | None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class HarnessAdapter(ABC):
    name: str

    @abstractmethod
    async def validate_configuration(self) -> list[str]: ...

    @abstractmethod
    async def prepare(self, request: HarnessRunRequest) -> None: ...

    @abstractmethod
    async def run(self, request: HarnessRunRequest) -> HarnessRunResult: ...

    @abstractmethod
    def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]: ...

    @abstractmethod
    async def cancel(self, run_id: str) -> None: ...

    @abstractmethod
    async def cleanup(self, run_id: str) -> None: ...


_REGISTRY: dict[str, HarnessAdapter] = {}


def register(adapter: HarnessAdapter) -> None:
    _REGISTRY[adapter.name] = adapter


def get_harness(name: str) -> HarnessAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"unknown harness: {name}")
    return _REGISTRY[name]


def list_harnesses() -> list[str]:
    return sorted(_REGISTRY)
