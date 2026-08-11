"""In-process asyncio queue worker (spec §13) behind a small interface.

Single-scheduler guard (eng review Tension 5): the worker refuses to start
twice in one process; `make dev` runs uvicorn without --workers so exactly
one scheduler exists. Concurrency is a semaphore (default 1, configurable).

Pipeline per run:
  PENDING → PREPARING (workspace snapshot; docker create+seal for sandboxed
            harnesses) → RUNNING (harness, proxy token issued) → EVALUATING
            (skeleton evaluator: patch produced?) → COMPLETED / FAILED
Pause = stop claiming new runs only (eng review Tension 5). Cancel kills the
container and marks CANCELLED. FAILED/TIMED_OUT retry back to PENDING.
"""

import asyncio
import hashlib
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.proxy import issue_run_token, revoke_run_token
from app.core.config import settings
from app.core.errors import ErrorCategory
from app.harnesses.base import HarnessRunRequest, get_harness
from app.models import (
    Artifact,
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentCombination,
    HiddenTestCandidate,
    RunEvent,
)
from app.models.core import VALID_TRANSITIONS, RunState

log = logging.getLogger(__name__)

SANDBOXED_HARNESSES = {"mini-swe-agent"}
# Sandboxed harnesses reach the proxy through the host gateway on the port
# uvicorn actually listens on (Makefile `backend` target and settings agree).
DOCKER_PROXY_BASE = f"http://host.docker.internal:{settings.backend_port}/proxy"


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
        concurrency: int | None = None,
        sandbox_manager: Any | None = None,
    ) -> None:
        self._sessions = session_factory
        self._proxy_base_url = proxy_base_url
        self._poll_interval = poll_interval
        self._semaphore = asyncio.Semaphore(concurrency or settings.queue_concurrency)
        self._sandboxes = sandbox_manager
        self._task: asyncio.Task[None] | None = None
        self._active: dict[str, asyncio.Task[None]] = {}
        self._stopping = asyncio.Event()
        self._paused_experiments: set[str] = set()
        self.paused = False

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
        for task in list(self._active.values()):
            task.cancel()

    def pause_experiment(self, experiment_id: str) -> None:
        self._paused_experiments.add(experiment_id)

    def resume_experiment(self, experiment_id: str) -> None:
        self._paused_experiments.discard(experiment_id)

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a queued or active run. Active: kill container + task."""
        if self._sandboxes is not None:
            await self._sandboxes.kill(run_id)
        task = self._active.get(run_id)
        if task is not None:
            task.cancel()
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None:
                return False
            state = RunState(run.state)
            if RunState.CANCELLED not in VALID_TRANSITIONS[state]:
                return False
            run.state = RunState.CANCELLED
            run.error_category = ErrorCategory.CANCELLED
            run.completed_at = datetime.now(UTC)
            self._event(session, run_id, "cancelled", {})
            session.commit()
        return True

    @staticmethod
    def retry_run(session: Session, run_id: str) -> bool:
        run = session.get(BenchmarkRun, run_id)
        if run is None or RunState.PENDING not in VALID_TRANSITIONS[RunState(run.state)]:
            return False
        run.state = RunState.PENDING
        run.error_category = None
        run.error_message = None
        session.commit()
        return True

    async def _loop(self) -> None:
        log.info("queue worker started", extra={"event_type": "worker_start"})
        while not self._stopping.is_set():
            claimed = None if self.paused else self._claim_next()
            if claimed is None:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
                continue
            task = asyncio.create_task(self._run_guarded(claimed))
            self._active[claimed] = task

            def _done(_t: asyncio.Task[None], rid: str = claimed) -> None:
                self._active.pop(rid, None)

            task.add_done_callback(_done)
        for task in list(self._active.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _claim_next(self) -> str | None:
        with self._sessions() as session:
            pending = session.scalars(
                select(BenchmarkRun)
                .where(BenchmarkRun.state == RunState.PENDING)
                .order_by(BenchmarkRun.created_at)
            ).all()
            for run in pending:
                combo = session.get(ExperimentCombination, run.combination_id)
                if combo is not None and combo.experiment_id in self._paused_experiments:
                    continue
                run_id = run.id
                transition(run, RunState.PREPARING)
                session.commit()
                return run_id
        return None

    async def _run_guarded(self, run_id: str) -> None:
        async with self._semaphore:
            try:
                await self._execute(run_id)
            except asyncio.CancelledError:
                log.info("run cancelled", extra={"run_id": run_id, "event_type": "run_cancelled"})
            except Exception as exc:  # noqa: BLE001 - categorize, never crash the loop
                log.exception("run failed", extra={"run_id": run_id, "event_type": "run_failed"})
                self._fail(run_id, ErrorCategory.HARNESS, str(exc))

    def _fail(self, run_id: str, category: ErrorCategory, message: str) -> None:
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None or RunState(run.state) in (RunState.CANCELLED, RunState.COMPLETED):
                return
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
            config = dict(experiment.config)
            self._event(session, run_id, "preparing", {})
            session.commit()

        sandboxed = harness_name in SANDBOXED_HARNESSES and self._sandboxes is not None
        workspace = Path(tempfile.mkdtemp(prefix=f"aso-{run_id[:8]}-"))
        try:
            fixture = config.get("fixture_path")
            if fixture:
                shutil.copytree(fixture, workspace, dirs_exist_ok=True)

            token = issue_run_token(
                run_id,
                model_id,
                max_requests=int(config.get("max_model_requests", 50)),
                max_cost_usd=config.get("max_cost_usd"),
            )
            proxy_base = self._proxy_base_url
            if sandboxed:
                assert self._sandboxes is not None
                await self._sandboxes.create(run_id, workspace)
                await self._sandboxes.seal(run_id)
                proxy_base = DOCKER_PROXY_BASE

            harness = get_harness(harness_name)
            request = HarnessRunRequest(
                task_id=task_id,
                task_prompt=prompt,
                workspace_path=workspace,
                model_id=model_id,
                provider=provider,
                timeout_seconds=int(config.get("timeout_seconds", 1800)),
                max_steps=int(config.get("max_steps", 50)),
                temperature=float(config.get("temperature", 0.0)),
                metadata={"run_id": run_id},
                proxy_base_url=proxy_base,
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

            patch_produced = bool(result.patch and result.patch.strip())
            if patch_produced:
                self._store_patch(run_id, result.patch or "")
            evaluation = await asyncio.to_thread(
                self._evaluate, run_id, task_id, result.patch, config
            )

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                if result.status == "completed":
                    transition(run, RunState.COMPLETED)
                    run.error_category = ErrorCategory.NONE
                elif result.status == "timeout":
                    transition(run, RunState.TIMED_OUT)
                    run.error_category = ErrorCategory.TIMEOUT
                else:
                    transition(run, RunState.FAILED)
                    run.error_category = ErrorCategory.HARNESS
                    run.error_message = (result.error_message or "")[:2000]
                run.completed_at = datetime.now(UTC)
                run.result = {
                    "status": result.status,
                    "patch_produced": patch_produced,
                    "final_message": result.final_message,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "model_requests": result.model_requests,
                    "agent_steps": result.agent_steps,
                    "commands_executed": result.commands_executed,
                    "evaluation_signal": evaluation.get("signal"),
                    "score": evaluation.get("score"),
                }
                self._event(session, run_id, result.status, {"patch_produced": patch_produced})
                session.commit()
        finally:
            revoke_run_token(run_id)
            if sandboxed and self._sandboxes is not None:
                await self._sandboxes.cleanup(run_id)
            shutil.rmtree(workspace, ignore_errors=True)

    def _evaluate(
        self, run_id: str, task_id: str, patch: str | None, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Grade the patch on a fresh snapshot (Tension 2) and persist results."""
        import tempfile

        from sqlalchemy import select as sa_select

        from app.evaluators.engine import EvaluationContext, evaluate
        from app.models import EvaluationResult

        snapshot_source = config.get("fixture_path")
        if not snapshot_source:
            return {"signal": "no_evaluation_configured", "score": None}
        with self._sessions() as session:
            hidden = {
                c.relpath: c.content
                for c in session.scalars(
                    sa_select(HiddenTestCandidate).where(
                        HiddenTestCandidate.task_id == task_id,
                        HiddenTestCandidate.approved.is_(True),
                    )
                )
            }
        context = EvaluationContext(
            patch=patch,
            snapshot_source=Path(snapshot_source),
            commands=dict(config.get("commands", {"test": "pytest -v"})),
            test_framework=config.get("test_framework", "pytest"),
            baseline_cases=[tuple(c) for c in config.get("baseline_cases", [])],
            hidden_tests=hidden,
        )
        with tempfile.TemporaryDirectory(prefix=f"aso-eval-{run_id[:8]}-") as tmp:
            outcome = evaluate(context, Path(tmp))
        with self._sessions() as session:
            session.add(
                EvaluationResult(
                    run_id=run_id,
                    signal=outcome.signal,
                    score=outcome.score,
                    results=outcome.results,
                )
            )
            session.commit()
        return {"signal": outcome.signal, "score": outcome.score}

    def _store_patch(self, run_id: str, patch: str) -> None:
        """Atomic artifact write (tmp+rename) with checksum in DB."""
        artifacts_dir = settings.data_dir.resolve() / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        final = artifacts_dir / f"{run_id}.patch"
        tmp = final.with_suffix(".patch.tmp")
        tmp.write_text(patch)
        tmp.rename(final)
        checksum = hashlib.sha256(patch.encode()).hexdigest()
        with self._sessions() as session:
            session.add(Artifact(run_id=run_id, kind="patch", path=str(final), checksum=checksum))
            session.commit()

    @staticmethod
    def _event(session: Session, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        session.add(RunEvent(run_id=run_id, event_type=event_type, payload=payload))
