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
