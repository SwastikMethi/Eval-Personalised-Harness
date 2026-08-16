"""Harness adapter contract (spec §3). All harnesses normalize to HarnessRunResult."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MISSING_MARKERS = ("command not found", "no module named", "modulenotfounderror")


def probe_failed(dependency: str, command: str, result: Any) -> Exception:
    """Explain a failed dependency probe without overclaiming.

    Both adapters used to raise "<dep> missing in sandbox image" on ANY non-zero
    exit, so when a container was already dying the run reported a missing
    dependency. That message was false — the image installs both harnesses and
    they import cleanly — and it sent a debugging session after an image problem
    that did not exist. Only claim absence when the output actually says so.

    Returns SandboxError so the orchestrator files it as SETUP, not as a harness
    crash: a probe that could not run is not the harness misbehaving.
    """
    from app.sandboxes.manager import SandboxError

    output = f"{result.stdout}{result.stderr}".strip()
    if any(marker in output.lower() for marker in _MISSING_MARKERS):
        detail = f"{dependency} is not installed in the sandbox image"
    else:
        detail = (
            f"could not verify {dependency}: the probe exited {result.exit_code} "
            f"without saying it is absent, so this is a sandbox failure rather "
            f"than a missing dependency"
        )
    return SandboxError(f"{detail}. `{command}` output: {output[-300:] or '(none)'}")


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


# How a harness hands back what the agent changed. Identical for every harness,
# so it lives here rather than being retyped per adapter.
#
# `--binary` and the two exclusions are both load-bearing, and were paid for:
# a mini-swe-agent run wrote a correct two-file fix, and the whole patch was
# rejected with "cannot apply binary patch to 'src/__pycache__/…pyc' without
# full index line" because running the code had regenerated eight .pyc files
# that `git add -A` swept up. The run scored 0.0 for work it had actually done,
# and the hidden test never got to run at all.
#
# Compiled Python is excluded rather than made appliable: it is derived from
# the .py files in the same patch, so grading it is meaningless even when it
# applies. `--binary` stays for the genuine case — an agent that legitimately
# adds or edits a binary asset should still be gradeable.
PATCH_EXTRACT_COMMAND = (
    "git add -A && git diff --cached --binary -- . "
    "':(exclude)**/__pycache__/**' ':(exclude)**/*.py[co]'"
)

_REGISTRY: dict[str, HarnessAdapter] = {}


def register(adapter: HarnessAdapter) -> None:
    _REGISTRY[adapter.name] = adapter


def get_harness(name: str) -> HarnessAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"unknown harness: {name}")
    return _REGISTRY[name]


def list_harnesses() -> list[str]:
    return sorted(_REGISTRY)
