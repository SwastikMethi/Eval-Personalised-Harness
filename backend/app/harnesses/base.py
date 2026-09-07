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
    # A comprehension task is answered, a commit task is patched. The adapter
    # needs to know which so it can ask for the answer in its own idiom.
    task_kind: str = "commit"


# How a comprehension answer is delivered, appended by the ADAPTER rather than
# baked into the task prompt.
#
# It used to be baked in at task-creation time (`tasks_api.py`), which fixed one
# convention — write ANSWER.md — before any harness was known. That convention
# comes from mini-SWE-agent's shell loop, and handing it to a smolagents
# CodeAgent produced runs that reported "Successfully wrote comprehensive
# analysis to ANSWER.md" while the collected patch was empty: the agent had
# spent 12k output tokens on analysis, then returned a 497-character summary
# through `final_answer` and filed nothing. Grading an agent on whether it
# obeyed a filing convention measures the convention.
DELIVER_AS_FILE = (
    "\n\nThe ONLY file you may create or modify is ANSWER.md in the repository "
    "root — write your complete answer there, in Markdown, with no length "
    "limit. Writing ANSWER.md is the last thing you should do; do not finish "
    "without it. If for any reason you cannot write the file, put the complete "
    "answer in your final message instead. An empty or one-line ending is a "
    "failed attempt, however much you learned along the way."
    # …and then say so. Without this the instruction only ever forbids
    # finishing and never releases that constraint, so an agent that had
    # already done the job kept going: one run wrote a complete ANSWER.md
    # early, explored for roughly 120 more steps, and was killed at 6,030,328
    # input tokens by the ceiling. There is nothing left to find once the
    # answer is written.
    "\n\nAs soon as ANSWER.md is written, submit and end the run. Do not keep "
    "exploring, re-reading files, or revising — the task is complete at that "
    "point, and continuing costs budget without improving the answer."
)

DELIVER_AS_FINAL_ANSWER = (
    "\n\nDeliver your answer by calling final_answer() with the COMPLETE text, "
    "in Markdown, with no length limit. That call is the answer of record — a "
    "summary of what you found is not an answer, and anything you leave in "
    "intermediate output is not read. Do not create or modify any file; a note "
    "saying you wrote the answer somewhere counts as no answer at all."
)


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
