"""smolagents adapter, against a stubbed sandbox (no Docker required).

The behaviours worth pinning: the run token never leaks into the workspace,
the runner lives in /tmp so it cannot pollute the collected patch, and real
token usage is reported rather than fabricated.
"""

import base64
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.harnesses.base import HarnessRunRequest
from app.harnesses.smolagents_agent import (
    RESULT_PATH,
    RUNNER_PATH,
    TASK_PATH,
    SmolagentsHarness,
)
from app.sandboxes.exec import CommandResult

PATCH = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-return 1\n+return 2\n"


class StubSandbox:
    """Records commands and answers them the way a real container would."""

    def __init__(self, report: dict[str, Any] | str, patch: str = PATCH) -> None:
        self.commands: list[str] = []
        self._report = report if isinstance(report, str) else json.dumps(report)
        self._patch = patch
        self.files: dict[str, str] = {}

    async def exec(self, run_id: str, command: str, timeout_s: int = 600) -> CommandResult:
        self.commands.append(command)
        stdout = ""
        # Emulate the base64 write-to-file idiom the adapter uses. shlex.quote
        # leaves pure base64 unquoted, so both forms have to be handled.
        if match := re.match(
            r"printf %s '?([A-Za-z0-9+/=]+)'? \| base64 -d > '?([^'\s]+)'?", command
        ):
            self.files[match.group(2)] = base64.b64decode(match.group(1)).decode()
        elif "git diff --cached" in command:
            stdout = self._patch
        elif command.startswith(f"cat {RESULT_PATH}"):
            stdout = self._report
        elif "import smolagents" in command:
            stdout = "1.26.0"
        return CommandResult(
            command=command, exit_code=0, stdout=stdout, stderr="", duration_s=0.1
        )

    async def kill(self, run_id: str) -> None: ...
    async def cleanup(self, run_id: str) -> None: ...


def _request(tmp_path: Path) -> HarnessRunRequest:
    return HarnessRunRequest(
        task_id="t1",
        task_prompt="Fix median() for even-length lists",
        workspace_path=tmp_path,
        model_id="openai/gpt-oss-20b:free",
        provider="openrouter",
        timeout_seconds=600,
        max_steps=8,
        temperature=0.0,
        metadata={"run_id": "run-1"},
        proxy_base_url="http://host.docker.internal:8005/proxy",
        run_token="secret-run-token",
    )


async def test_reports_real_usage_and_patch(tmp_path: Path) -> None:
    sandbox = StubSandbox(
        {
            "status": "completed",
            "final_message": "fixed it",
            "steps": 3,
            "tool_calls": 2,
            "input_tokens": 1234,
            "output_tokens": 56,
        }
    )
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)
    await harness.prepare(request)
    result = await harness.run(request)

    assert result.status == "completed"
    assert result.patch == PATCH
    assert result.final_message == "fixed it"
    assert result.agent_steps == 3
    assert result.tool_calls == 2
    # smolagents does report usage — recording it is honest, inventing is not.
    assert (result.input_tokens, result.output_tokens) == (1234, 56)


async def test_runner_and_task_live_outside_the_workspace(tmp_path: Path) -> None:
    sandbox = StubSandbox({"status": "completed", "steps": 1})
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)
    await harness.prepare(request)
    await harness.run(request)

    # Anything written under /workspace would show up in `git diff --cached`
    # and be graded as part of the agent's patch.
    assert RUNNER_PATH.startswith("/tmp/")
    for path in sandbox.files:
        assert path.startswith("/tmp/"), f"{path} would pollute the patch"
    assert "smolagents" in sandbox.files[RUNNER_PATH]
    assert sandbox.files["/tmp/aso_task.txt"] == request.task_prompt


async def test_token_is_passed_as_env_not_written_to_disk(tmp_path: Path) -> None:
    sandbox = StubSandbox({"status": "completed", "steps": 1})
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)
    await harness.prepare(request)
    await harness.run(request)

    run_cmd = next(c for c in sandbox.commands if RUNNER_PATH in c and "OPENAI_API_KEY" in c)
    assert "secret-run-token" in run_cmd
    assert "8005/proxy/v1" in run_cmd
    # The real key must never be anywhere near the container.
    assert not any("sk-or-" in c for c in sandbox.commands)
    for content in sandbox.files.values():
        assert "secret-run-token" not in content


async def test_agent_failure_is_categorized_not_swallowed(tmp_path: Path) -> None:
    sandbox = StubSandbox(
        {"status": "failed", "error_type": "AgentMaxStepsError", "error_message": "out of steps"},
        patch="",
    )
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]
    result = await harness.run(_request(tmp_path))

    assert result.status == "failed"
    assert result.error_type == "AgentMaxStepsError"
    assert result.patch is None  # empty patch is a real result, not an error


async def test_unparseable_report_does_not_crash_the_run(tmp_path: Path) -> None:
    harness = SmolagentsHarness(StubSandbox("not json at all"))  # type: ignore[arg-type]
    result = await harness.run(_request(tmp_path))
    assert result.status == "failed"
    assert result.input_tokens is None  # never fabricate


async def test_prepare_fails_loudly_when_smolagents_is_missing(tmp_path: Path) -> None:
    class Missing(StubSandbox):
        async def exec(self, run_id: str, command: str, timeout_s: int = 600) -> CommandResult:
            if "import smolagents" in command:
                # What an absent module actually prints. Exit 1 with no output
                # is what a dying container looks like, and the adapter used to
                # report both as a missing dependency.
                return CommandResult(
                    command=command,
                    exit_code=1,
                    stdout="",
                    stderr="ModuleNotFoundError: No module named 'smolagents'",
                    duration_s=0.1,
                )
            return await super().exec(run_id, command, timeout_s)

    from app.sandboxes.manager import SandboxError

    harness = SmolagentsHarness(Missing({}))  # type: ignore[arg-type]
    with pytest.raises(SandboxError, match="not installed in the sandbox image"):
        await harness.prepare(_request(tmp_path))


async def test_a_comprehension_task_is_asked_for_final_answer_not_a_file(
    tmp_path: Path,
) -> None:
    """A CodeAgent exits through final_answer(); asking it to file a document
    produced runs that claimed to have written ANSWER.md and returned a
    497-character summary with an empty patch.
    """
    from app.harnesses.base import DELIVER_AS_FINAL_ANSWER

    sandbox = StubSandbox({"status": "completed", "final_message": "answer", "steps": 4})
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)
    request.task_kind = "theory"

    await harness.run(request)

    delivered = sandbox.files[TASK_PATH]
    assert DELIVER_AS_FINAL_ANSWER.strip() in delivered
    assert "ANSWER.md" not in delivered


async def test_a_commit_task_gets_no_answer_instruction(tmp_path: Path) -> None:
    """A commit replay answers with a patch; an answer convention would be noise."""
    sandbox = StubSandbox({"status": "completed", "final_message": "done", "steps": 3})
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)  # defaults to kind "commit"

    await harness.run(request)

    assert sandbox.files[TASK_PATH] == request.task_prompt


async def test_steps_are_not_reported_as_model_requests(tmp_path: Path) -> None:
    """A measured run took 4 steps and made 11 upstream calls. The proxy counts
    requests; the harness must not put a different quantity behind that name.
    """
    sandbox = StubSandbox({"status": "completed", "final_message": "a", "steps": 4})
    harness = SmolagentsHarness(sandbox)  # type: ignore[arg-type]

    result = await harness.run(_request(tmp_path))

    assert result.model_requests is None
    assert result.agent_steps == 4
