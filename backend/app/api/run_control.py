from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import Experiment
from app.orchestration.queue import QueueWorker

router = APIRouter()


def _worker(request: Request) -> QueueWorker:
    worker = getattr(request.app.state, "worker", None)
    if not isinstance(worker, QueueWorker):
        raise HTTPException(503, "queue worker not running")
    return worker


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict[str, Any]:
    if not await _worker(request).cancel_run(run_id):
        raise HTTPException(409, "run cannot be cancelled from its current state")
    return {"ok": True}


@router.post("/runs/{run_id}/retry")
def retry_run(
    run_id: str, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    if not QueueWorker.retry_run(session, run_id):
        raise HTTPException(409, "run is not retryable from its current state")
    return {"ok": True}


@router.post("/experiments/{experiment_id}/pause")
def pause_experiment(
    experiment_id: str, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    _worker(request).pause_experiment(experiment_id)
    exp.status = "paused"
    session.commit()
    return {"ok": True}


@router.post("/experiments/{experiment_id}/cancel")
async def cancel_experiment(
    experiment_id: str, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Cancel every non-terminal run in an experiment (spec §19)."""
    from sqlalchemy import select

    from app.models import BenchmarkRun, ExperimentCombination
    from app.models.core import TERMINAL_STATES, RunState

    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    worker = _worker(request)
    worker.pause_experiment(experiment_id)  # stop claiming while we cancel

    combo_ids = session.scalars(
        select(ExperimentCombination.id).where(
            ExperimentCombination.experiment_id == experiment_id
        )
    ).all()
    run_ids = (
        session.scalars(
            select(BenchmarkRun.id).where(BenchmarkRun.combination_id.in_(list(combo_ids)))
        ).all()
        if combo_ids
        else []
    )
    cancelled = 0
    for run_id in run_ids:
        run = session.get(BenchmarkRun, run_id)
        if run is None or RunState(run.state) in TERMINAL_STATES:
            continue
        if await worker.cancel_run(run_id):
            cancelled += 1
    exp.status = "cancelled"
    session.commit()
    return {"ok": True, "cancelled": cancelled}


@router.post("/experiments/{experiment_id}/resume")
def resume_experiment(
    experiment_id: str, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    _worker(request).resume_experiment(experiment_id)
    exp.status = "running"
    session.commit()
    return {"ok": True}
