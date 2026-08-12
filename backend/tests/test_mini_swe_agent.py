"""mini-SWE-agent adapter, against a stubbed sandbox (no Docker required).

Regression cover for a bug that made this harness unusable: `prepare()`
passed `request.task_id` to the sandbox manager, which keys containers by
run_id, so every sandboxed run died with KeyError during PREPARING before the
agent started. Nothing caught it because no test exercised the real
manager-keying contract.
"""

from pathlib import Path

import pytest

from app.harnesses.base import HarnessRunRequest
from app.harnesses.mini_swe_agent import MiniSweAgentHarness
from app.sandboxes.exec import CommandResult

RUN_ID = "run-abc"
TASK_ID = "task-xyz"


class KeyedSandbox:
    """Mimics SandboxManager: only the registered run_id resolves."""

    def __init__(self) -> None:
        self.containers = {RUN_ID: object()}
        self.seen_ids: list[str] = []

    async def exec(self, run_id: str, command: str, timeout_s: int = 600) -> CommandResult:
        self.seen_ids.append(run_id)
        if run_id not in self.containers:
            raise KeyError(run_id)
        stdout = ""
        if "git diff --cached" in command:
            stdout = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-1\n+2\n"
        elif command.startswith("cat "):
            stdout = '{"messages": [{"role": "user", "content": "t"}, '\
                     '{"role": "assistant", "content": "done"}]}'
        return CommandResult(
            command=command, exit_code=0, stdout=stdout, stderr="", duration_s=0.1
        )

    async def kill(self, run_id: str) -> None: ...
    async def cleanup(self, run_id: str) -> None: ...


def _request(tmp_path: Path) -> HarnessRunRequest:
    return HarnessRunRequest(
        task_id=TASK_ID,
        task_prompt="fix it",
        workspace_path=tmp_path,
        model_id="openai/gpt-oss-20b:free",
        provider="openrouter",
        timeout_seconds=600,
        max_steps=8,
        temperature=0.0,
        metadata={"run_id": RUN_ID},
        proxy_base_url="http://host.docker.internal:8005/proxy",
        run_token="secret-run-token",
    )


async def test_registry_carries_the_key_litellm_actually_looks_up(tmp_path: Path) -> None:
    """The defect that made this harness produce nothing at all.

    LitellmModel.query prices with `completion_cost(response)`, so litellm looks
    up the model name in the RESPONSE. Our proxy echoes back `body.model` — the
    bare id litellm sent after stripping its own `openai/` routing prefix — so a
    registry containing only "openai/<id>" never matched. litellm raised, mini
    re-raised, and the agent exited 0 after ZERO steps: recorded COMPLETED, no
    patch, score 0.0, measuring this wiring rather than the model.
    """
    import base64
    import json

    class Capturing(KeyedSandbox):
        def __init__(self) -> None:
            super().__init__()
            self.registry: dict[str, object] = {}

        async def exec(self, run_id: str, command: str, timeout_s: int = 600) -> CommandResult:
            if "base64 -d >" in command and "registry" in command:
                blob = command.split("printf %s ")[1].split(" |")[0].strip("'\"")
                self.registry = json.loads(base64.b64decode(blob).decode())
            return await super().exec(run_id, command, timeout_s)

    sandbox = Capturing()
    harness = MiniSweAgentHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)
    await harness.prepare(request)
    await harness.run(request)

    # The bare id is what comes back in the response and therefore what is
    # priced; the prefixed one is what litellm was configured with.
    assert request.model_id in sandbox.registry, "the response's model name must be priceable"
    assert f"openai/{request.model_id}" in sandbox.registry
    for entry in sandbox.registry.values():
        assert entry["litellm_provider"] == "openai"  # type: ignore[index]
        assert entry["input_cost_per_token"] == 0.0  # type: ignore[index]


async def test_prepare_addresses_the_container_by_run_id(tmp_path: Path) -> None:
    sandbox = KeyedSandbox()
    harness = MiniSweAgentHarness(sandbox)  # type: ignore[arg-type]
    await harness.prepare(_request(tmp_path))
    assert sandbox.seen_ids == [RUN_ID]
    assert TASK_ID not in sandbox.seen_ids


async def test_run_collects_patch_and_never_leaks_the_real_key(tmp_path: Path) -> None:
    sandbox = KeyedSandbox()
    harness = MiniSweAgentHarness(sandbox)  # type: ignore[arg-type]
    request = _request(tmp_path)
    await harness.prepare(request)
    result = await harness.run(request)

    assert result.status == "completed"
    assert result.patch is not None and "app.py" in result.patch
    assert set(sandbox.seen_ids) == {RUN_ID}
    # Token usage is not reported reliably by this harness — leave it null
    # rather than inventing numbers (spec §31).
    assert result.input_tokens is None


async def test_prepare_fails_loudly_when_cli_is_missing(tmp_path: Path) -> None:
    class NoCli(KeyedSandbox):
        async def exec(self, run_id: str, command: str, timeout_s: int = 600) -> CommandResult:
            self.seen_ids.append(run_id)
            # Say what a genuinely absent binary says. The previous fixture
            # returned exit 1 with no output at all, which is indistinguishable
            # from a container that died — and the adapter claimed a missing
            # dependency for both.
            return CommandResult(
                command=command,
                exit_code=127,
                stdout="",
                stderr="sh: 1: mini: command not found",
                duration_s=0.1,
            )

    from app.sandboxes.manager import SandboxError

    harness = MiniSweAgentHarness(NoCli())  # type: ignore[arg-type]
    with pytest.raises(SandboxError, match="not installed in the sandbox image"):
        await harness.prepare(_request(tmp_path))
