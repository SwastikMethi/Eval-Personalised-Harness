"""In-process asyncio queue worker (spec §13) behind a small interface.

Single-scheduler guard (eng review Tension 5): the worker refuses to start
twice in one process; `make dev` runs uvicorn without --workers so exactly
one scheduler exists.

Stage-1 pipeline per run:
  PENDING → PREPARING (workspace from fixture snapshot)
          → RUNNING   (harness, proxy token issued)
          → EVALUATING (skeleton evaluator: patch produced?)
          → COMPLETED / FAILED(ErrorCategory)
"""

import asyncio
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.proxy import issue_run_token, revoke_run_token
from app.core.errors import ErrorCategory
from app.harnesses.base import HarnessRunRequest, get_harness
from app.models import BenchmarkRun, BenchmarkTask, Experiment, ExperimentCombination, RunEvent
from app.models.core import VALID_TRANSITIONS, RunState

log = logging.getLogger(__name__)


def transition(run: BenchmarkRun, new_state: RunState) -> None:
    current = RunState(run.state)
    if new_state not in VALID_TRANSITIONS[current]:
        raise ValueError(f"invalid transition {current} -> {new_state}")
    run.state = new_state


class QueueWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        proxy_base_url: str,
        poll_interval: float = 0.2,
    ) -> None:
        self._sessions = session_factory
        self._proxy_base_url = proxy_base_url
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("queue worker already started in this process")
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="queue-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            await self._task
            self._task = None

    async def _loop(self) -> None:
        log.info("queue worker started", extra={"event_type": "worker_start"})
        while not self._stopping.is_set():
            processed = await self._process_next()
            if not processed:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._poll_interval
                    )
                except TimeoutError:
                    pass

    async def _process_next(self) -> bool:
        with self._sessions() as session:
            run = session.scalars(
                select(BenchmarkRun)
                .where(BenchmarkRun.state == RunState.PENDING)
                .order_by(BenchmarkRun.created_at)
                .limit(1)
            ).first()
            if run is None:
                return False
            run_id = run.id
            transition(run, RunState.PREPARING)
            session.commit()
        try:
            await self._execute(run_id)
        except Exception as exc:  # noqa: BLE001 - every failure must be categorized, never crash the loop
            log.exception("run failed", extra={"run_id": run_id, "event_type": "run_failed"})
            self._fail(run_id, ErrorCategory.HARNESS, str(exc))
        return True

    def _fail(self, run_id: str, category: ErrorCategory, message: str) -> None:
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None:
                return
            if RunState(run.state) is not RunState.FAILED:
                run.state = RunState.FAILED
            run.error_category = category
            run.error_message = message[:2000]
            run.completed_at = datetime.now(UTC)
            session.commit()

    async def _execute(self, run_id: str) -> None:
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            assert run is not None
            combo = session.get(ExperimentCombination, run.combination_id)
            assert combo is not None
            task = session.get(BenchmarkTask, combo.task_id)
            experiment = session.get(Experiment, combo.experiment_id)
            assert task is not None and experiment is not None
            harness_name, model_id, provider = combo.harness, combo.model_id, combo.provider
            prompt, task_id = task.prompt, task.id
            fixture = experiment.config.get("fixture_path")
            self._event(session, run_id, "preparing", {})
            session.commit()

        workspace = Path(tempfile.mkdtemp(prefix=f"aso-{run_id[:8]}-"))
        try:
            if fixture:
                shutil.copytree(fixture, workspace, dirs_exist_ok=True)

            token = issue_run_token(run_id, model_id)
            harness = get_harness(harness_name)
            request = HarnessRunRequest(
                task_id=task_id,
                task_prompt=prompt,
                workspace_path=workspace,
                model_id=model_id,
                provider=provider,
                timeout_seconds=1800,
                max_steps=50,
                temperature=0.0,
                proxy_base_url=self._proxy_base_url,
                run_token=token,
            )
            await harness.prepare(request)

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                transition(run, RunState.RUNNING)
                run.started_at = datetime.now(UTC)
                run.heartbeat_at = run.started_at
                self._event(session, run_id, "running", {"harness": harness_name})
                session.commit()

            result = await harness.run(request)

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                transition(run, RunState.EVALUATING)
                self._event(session, run_id, "evaluating", {})
                session.commit()

            # Skeleton evaluator: a patch was produced. Real evaluators land Stage 5.
            patch_produced = bool(result.patch and result.patch.strip())

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                transition(run, RunState.COMPLETED)
                run.completed_at = datetime.now(UTC)
                run.error_category = ErrorCategory.NONE
                run.result = {
                    "status": result.status,
                    "patch_produced": patch_produced,
                    "final_message": result.final_message,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "model_requests": result.model_requests,
                }
                self._event(session, run_id, "completed", {"patch_produced": patch_produced})
                session.commit()
        finally:
            revoke_run_token(run_id)
            shutil.rmtree(workspace, ignore_errors=True)

    @staticmethod
    def _event(session: Session, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        session.add(RunEvent(run_id=run_id, event_type=event_type, payload=payload))
