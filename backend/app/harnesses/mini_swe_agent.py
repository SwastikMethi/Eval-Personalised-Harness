"""mini-SWE-agent adapter (eng review 3A: harness runs INSIDE the sandbox).

Verified against current docs (mini-swe-agent.com, 2026-07): CLI entrypoint
`mini`, litellm model backend, yolo (non-interactive) mode, OpenAI-compatible
endpoints via `openai/<model>` naming with OPENAI_API_KEY + OPENAI_BASE_URL.
The container gets ONLY the per-run proxy token — never the real key.
Version pinned in sandbox-images/python/Dockerfile.
"""

import base64
import json
import shlex
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.harnesses.base import HarnessAdapter, HarnessRunRequest, HarnessRunResult
from app.sandboxes.manager import SandboxManager

TRAJECTORY_PATH = "/tmp/mini-trajectory.json"
REGISTRY_PATH = "/tmp/aso_litellm_registry.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MiniSweAgentHarness(HarnessAdapter):
    name = "mini-swe-agent"

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    async def validate_configuration(self) -> list[str]:
        from app.sandboxes.manager import docker_available

        return [] if docker_available() else ["docker is not available"]

    async def prepare(self, request: HarnessRunRequest) -> None:
        # Containers are keyed by run_id, not task_id — passing task_id here
        # raised KeyError during PREPARING, so this harness could never
        # actually start in a sandbox.
        run_id = request.metadata["run_id"]
        check = await self._manager.exec(run_id, "mini --help", timeout_s=60)
        if check.exit_code != 0:
            raise RuntimeError("mini-swe-agent CLI missing in sandbox image")

    async def run(self, request: HarnessRunRequest) -> HarnessRunResult:
        started = _now()
        run_id = request.metadata["run_id"]
        # litellm needs the openai/ prefix to route to an OpenAI-compatible base URL.
        model = f"openai/{request.model_id}"

        # mini re-raises if litellm cannot price the model, which kills the run
        # after its first successful completion. litellm has no pricing for a
        # model served through our proxy, so register it explicitly via the
        # documented LITELLM_MODEL_REGISTRY_PATH hook. Zero is the true cost
        # for the pinned free variants; the proxy's ModelRequestMetric rows
        # remain the authoritative spend record either way.
        registry = json.dumps(
            {
                model: {
                    "input_cost_per_token": 0.0,
                    "output_cost_per_token": 0.0,
                    "litellm_provider": "openai",
                    "mode": "chat",
                }
            }
        )
        blob = base64.b64encode(registry.encode()).decode()
        await self._manager.exec(
            run_id,
            f"printf %s {shlex.quote(blob)} | base64 -d > {REGISTRY_PATH}",
            timeout_s=60,
        )
        cmd = (
            f"OPENAI_API_KEY={shlex.quote(request.run_token)} "
            f"OPENAI_BASE_URL={shlex.quote(request.proxy_base_url + '/v1')} "
            # Without MSWEA_CONFIGURED the CLI drops into an interactive
            # first-run wizard asking for a model and API key, which in a
            # non-tty sandbox just fails. Silent startup keeps the banner out
            # of the captured output.
            "MSWEA_CONFIGURED=true MSWEA_SILENT_STARTUP=1 "
            # Slow models exceed the client default and get abandoned mid-flight;
            # the abandoned request still completes upstream and spends quota.
            f"LITELLM_REQUEST_TIMEOUT={max(int(request.timeout_seconds) // 3, 120)} "
            "LITELLM_NUM_RETRIES=0 "
            f"LITELLM_MODEL_REGISTRY_PATH={REGISTRY_PATH} "
            f"mini -y -m {shlex.quote(model)} -t {shlex.quote(request.task_prompt)} "
            f"-o {TRAJECTORY_PATH} --exit-immediately"
        )
        result = await self._manager.exec(run_id, cmd, timeout_s=request.timeout_seconds)

        patch_result = await self._manager.exec(
            run_id, "git add -A && git diff --cached", timeout_s=120
        )
        patch = patch_result.stdout if patch_result.exit_code == 0 else None

        steps, model_requests, commands, final_message = self._parse_trajectory(
            (await self._manager.exec(run_id, f"cat {TRAJECTORY_PATH}", timeout_s=30)).stdout
        )

        if result.timed_out:
            status, error_type, error_message = "timeout", "timeout", "harness timed out"
        elif result.exit_code != 0:
            status, error_type = "failed", "harness"
            error_message = result.stdout[-1000:]
        else:
            status, error_type, error_message = "completed", None, None

        return HarnessRunResult(
            status=status,
            final_message=final_message,
            patch=patch if patch and patch.strip() else None,
            started_at=started,
            completed_at=_now(),
            # Token usage flows through the proxy's ModelRequestMetric rows —
            # the harness itself does not report usage reliably; never fabricate.
            input_tokens=None,
            output_tokens=None,
            cached_tokens=None,
            model_requests=model_requests,
            agent_steps=steps,
            tool_calls=0,
            commands_executed=commands,
            error_type=error_type,
            error_message=error_message,
            raw_metadata={
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                # Kept even on success: a run that exits 0 having done nothing
                # is indistinguishable from a good one without it.
                "stdout_tail": result.stdout[-3000:],
            },
        )

    @staticmethod
    def _parse_trajectory(raw: str) -> tuple[int, int, int, str | None]:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return 0, 0, 0, None
        messages = data.get("messages", data if isinstance(data, list) else [])
        assistant = [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"]
        users = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        final = str(assistant[-1].get("content", "")) if assistant else None
        return len(assistant), len(assistant), max(len(users) - 1, 0), final

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        yield {"run_id": run_id, "event": "noop"}

    async def cancel(self, run_id: str) -> None:
        await self._manager.kill(run_id)

    async def cleanup(self, run_id: str) -> None:
        await self._manager.cleanup(run_id)
