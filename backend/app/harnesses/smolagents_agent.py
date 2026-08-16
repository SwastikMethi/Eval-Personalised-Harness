"""smolagents CodeAgent adapter (eng review 3A: harness runs INSIDE the sandbox).

Verified against smolagents 1.26.0 by introspection, not guessed:
  - `OpenAIServerModel(model_id, api_base, api_key)` targets any
    OpenAI-compatible endpoint, which is how it reaches the run-scoped proxy.
  - `CodeAgent(tools, model, max_steps, additional_authorized_imports)` and
    `run(task, return_full_result=True) -> RunResult(output, steps,
    token_usage, ...)`.
  - The local Python executor does NOT expose the `open` builtin, so the agent
    edits files through `pathlib`. Authorizing that import is what makes a
    patch possible at all — without it every run is an empty patch that looks
    like a model failure but is really a config bug.

Unlike mini-SWE-agent, smolagents reports real token usage, so it is recorded
rather than left null.

The runner and the task text live in the container's /tmp (tmpfs), never in
/workspace, so they cannot pollute the diff we collect as the agent's patch.
"""

import base64
import json
import shlex
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.harnesses.base import (
    PATCH_EXTRACT_COMMAND,
    HarnessAdapter,
    HarnessRunRequest,
    HarnessRunResult,
    probe_failed,
)
from app.sandboxes.manager import SandboxManager

RUNNER_PATH = "/tmp/aso_smolagents_runner.py"
TASK_PATH = "/tmp/aso_task.txt"
RESULT_PATH = "/tmp/aso_result.json"

# Enough to read/edit source and run the project's tests; deliberately not "*".
AUTHORIZED_IMPORTS = ["pathlib", "os", "sys", "re", "json", "shutil", "subprocess"]

RUNNER = '''
import json, os, sys

out = {"status": "failed", "steps": 0, "tool_calls": 0}
try:
    from smolagents import CodeAgent, OpenAIServerModel

    task = open(os.environ["ASO_TASK_FILE"]).read()
    model = OpenAIServerModel(
        model_id=os.environ["ASO_MODEL"],
        api_base=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        # A slow model routinely exceeds the client default: one measured run
        # took 630s per request while the client gave up around 31s, retried,
        # and every abandoned attempt still completed upstream and spent quota
        # the agent never saw. Fail once, visibly; the queue owns retrying.
        client_kwargs={
            "timeout": float(os.environ.get("ASO_REQUEST_TIMEOUT", "600")),
            "max_retries": 0,
        },
    )
    agent = CodeAgent(
        tools=[],
        model=model,
        max_steps=int(os.environ.get("ASO_MAX_STEPS", "8")),
        additional_authorized_imports=json.loads(os.environ["ASO_IMPORTS"]),
    )
    result = agent.run(task, return_full_result=True)
    steps = list(getattr(result, "steps", None) or [])
    out = {
        "status": "completed",
        # Was 4000, which silently cost a comprehension answer its marks: a run
        # came back at exactly 3,996 characters — cut off mid-thought by this
        # cap, then graded as if that was all the agent had to say. A final
        # message is an ANSWER channel, not a log line.
        "final_message": str(getattr(result, "output", "") or "")[:60000],
        "steps": len(steps),
        "tool_calls": sum(1 for s in steps if getattr(s, "tool_calls", None)),
    }
    usage = getattr(result, "token_usage", None)
    if usage is not None:
        out["input_tokens"] = getattr(usage, "input_tokens", None)
        out["output_tokens"] = getattr(usage, "output_tokens", None)
except Exception as exc:
    import traceback

    out["error_type"] = type(exc).__name__
    out["error_message"] = str(exc)[:2000]
    # smolagents wraps provider failures in a generic "Connection error",
    # which is useless for diagnosis without the underlying frames.
    out["traceback"] = traceback.format_exc()[-3000:]

with open(os.environ["ASO_OUT"], "w") as fh:
    json.dump(out, fh)
'''


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_file_cmd(path: str, content: str) -> str:
    """Materialize a file in the container without quoting hazards."""
    blob = base64.b64encode(content.encode()).decode()
    return f"printf %s {shlex.quote(blob)} | base64 -d > {shlex.quote(path)}"


class SmolagentsHarness(HarnessAdapter):
    name = "smolagents"

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    async def validate_configuration(self) -> list[str]:
        from app.sandboxes.manager import docker_available

        return [] if docker_available() else ["docker is not available"]

    async def prepare(self, request: HarnessRunRequest) -> None:
        run_id = request.metadata["run_id"]
        check = await self._manager.exec(
            run_id, "python3 -c 'import smolagents; print(smolagents.__version__)'", timeout_s=60
        )
        if check.exit_code != 0:
            raise probe_failed("smolagents", "import smolagents", check)
        await self._manager.exec(run_id, _write_file_cmd(RUNNER_PATH, RUNNER), timeout_s=60)

    async def run(self, request: HarnessRunRequest) -> HarnessRunResult:
        started = _now()
        run_id = request.metadata["run_id"]

        await self._manager.exec(
            run_id, _write_file_cmd(TASK_PATH, request.task_prompt), timeout_s=60
        )
        cmd = (
            f"OPENAI_API_KEY={shlex.quote(request.run_token)} "
            f"OPENAI_BASE_URL={shlex.quote(request.proxy_base_url + '/v1')} "
            f"ASO_MODEL={shlex.quote(request.model_id)} "
            f"ASO_TASK_FILE={TASK_PATH} ASO_OUT={RESULT_PATH} "
            f"ASO_MAX_STEPS={int(request.max_steps)} "
            f"ASO_REQUEST_TIMEOUT={max(int(request.timeout_seconds) // 3, 120)} "
            f"ASO_IMPORTS={shlex.quote(json.dumps(AUTHORIZED_IMPORTS))} "
            f"python3 {RUNNER_PATH}"
        )
        result = await self._manager.exec(run_id, cmd, timeout_s=request.timeout_seconds)

        patch_result = await self._manager.exec(
            run_id, PATCH_EXTRACT_COMMAND, timeout_s=120
        )
        patch = patch_result.stdout if patch_result.exit_code == 0 else None

        raw = (await self._manager.exec(run_id, f"cat {RESULT_PATH}", timeout_s=30)).stdout
        report = self._parse_report(raw)

        if result.timed_out:
            status, error_type, error_message = "timeout", "timeout", "harness timed out"
        elif report.get("status") == "completed":
            status, error_type, error_message = "completed", None, None
        else:
            status = "failed"
            error_type = report.get("error_type") or "harness"
            # stderr too: the streams are demuxed now, and a crash before the
            # runner writes its report leaves its only explanation on stderr.
            error_message = (
                report.get("error_message") or (result.stdout + result.stderr)[-1000:]
            )

        return HarnessRunResult(
            status=status,
            final_message=report.get("final_message"),
            patch=patch if patch and patch.strip() else None,
            started_at=started,
            completed_at=_now(),
            # smolagents reports usage; the proxy's ModelRequestMetric rows
            # remain the authoritative record either way.
            input_tokens=report.get("input_tokens"),
            output_tokens=report.get("output_tokens"),
            cached_tokens=None,
            model_requests=int(report.get("steps") or 0),
            agent_steps=int(report.get("steps") or 0),
            tool_calls=int(report.get("tool_calls") or 0),
            commands_executed=None,  # CodeAgent executes Python, not shell commands
            error_type=error_type,
            error_message=error_message,
            raw_metadata={
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                "traceback": report.get("traceback"),
                "stdout_tail": result.stdout[-2000:],
                # smolagents logs its reasoning to stderr, so stdout alone left
                # a completed run with no transcript to inspect at all.
                "stderr_tail": result.stderr[-4000:],
            },
        )

    @staticmethod
    def _parse_report(raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        yield {"run_id": run_id, "event": "noop"}

    async def cancel(self, run_id: str) -> None:
        await self._manager.kill(run_id)

    async def cleanup(self, run_id: str) -> None:
        await self._manager.cleanup(run_id)
