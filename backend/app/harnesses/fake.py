"""FakeHarness: deterministic, but exercises the REAL proxy protocol.

Per eng review (Codex batch): a fake that skips the proxy would let demo runs
go green without covering the adapter/provider plumbing — so this one makes an
actual HTTP call to the run-scoped proxy endpoint and acts on the response.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx

from app.harnesses.base import HarnessAdapter, HarnessRunRequest, HarnessRunResult


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakeHarness(HarnessAdapter):
    name = "fake"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # transport lets tests route the proxy call through ASGI in-process
        # while dev/demo hit the real HTTP listener — same code path either way.
        self._transport = transport

    async def validate_configuration(self) -> list[str]:
        return []

    async def prepare(self, request: HarnessRunRequest) -> None:
        if not request.workspace_path.is_dir():
            raise FileNotFoundError(f"workspace missing: {request.workspace_path}")

    async def run(self, request: HarnessRunRequest) -> HarnessRunResult:
        started = _now()
        async with httpx.AsyncClient(transport=self._transport) as client:
            resp = await client.post(
                f"{request.proxy_base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {request.run_token}"},
                json={
                    "model": request.model_id,
                    "messages": [{"role": "user", "content": request.task_prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})

        target = request.workspace_path / "AGENT_NOTES.md"
        target.write_text(f"# Agent notes\n\n{content}\n")
        patch = (
            "--- /dev/null\n"
            "+++ b/AGENT_NOTES.md\n"
            "@@ -0,0 +1,3 @@\n"
            "+# Agent notes\n"
            "+\n"
            f"+{content}\n"
        )
        return HarnessRunResult(
            status="completed",
            final_message=content,
            patch=patch,
            started_at=started,
            completed_at=_now(),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cached_tokens=0,
            model_requests=1,
            agent_steps=1,
            tool_calls=0,
            commands_executed=0,
            error_type=None,
            error_message=None,
            raw_metadata={"fake": True},
        )

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        yield {"run_id": run_id, "event": "noop"}

    async def cancel(self, run_id: str) -> None:
        return None

    async def cleanup(self, run_id: str) -> None:
        return None
