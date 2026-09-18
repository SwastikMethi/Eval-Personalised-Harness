"""Live experiment events over SSE (spec §5, §19) + run detail (spec §19).

SSE rather than WebSockets: the stream is one-directional and this keeps the
frontend to plain EventSource with no extra dependency.

Events are replayed from the persisted RunEvent table rather than an in-memory
bus, so a browser that connects late or reconnects still sees the whole run —
and the queue worker stays decoupled from whoever is watching.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import SessionLocal, get_session
from app.models import (
    Artifact,
    BenchmarkRun,
    BenchmarkTask,
    EvaluationResult,
    Experiment,
    ExperimentCombination,
    ModelRequestMetric,
    RunEvent,
)

router = APIRouter()

POLL_INTERVAL_S = 1.0
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


def _scores_from_verdicts(
    session: Session, run_ids: list[str]
) -> dict[str, float | None]:
    """Each run's score, computed from its stored verdicts.

    NOT `run.result["score"]`. That field is written once when the run ends, so
    anything wrong at that moment is frozen into the UI forever — and something
    was: it held `verdicts[0]`, the group's FIRST task, so a run whose two tasks
    scored 0.833 and 0.0 displayed 0.833 while the results page ranked it on the
    true mean of 0.417. Two screens, two numbers, one run.

    Deriving it here fixes every historical run without a backfill, and removes
    the class of bug rather than the instance: there is now one source for both
    surfaces, so they cannot disagree again.

    Newest-per-task, the same rule `results_api` applies — a re-evaluation
    supersedes rather than doubles. Measured: one run carried six verdict rows
    for two tasks, so a naive mean over rows would have been wrong.
    """
    if not run_ids:
        return {}
    rows = session.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id.in_(run_ids))
        .order_by(EvaluationResult.created_at.desc())
    ).all()
    latest: dict[str, dict[str | None, EvaluationResult]] = {}
    for ev in rows:
        latest.setdefault(ev.run_id, {}).setdefault(ev.task_id, ev)

    out: dict[str, float | None] = {}
    for run_id in run_ids:
        graded = [e.score for e in latest.get(run_id, {}).values() if e.score is not None]
        # None, not 0.0: a run with no verdict has no score, it did not score
        # zero (CLAUDE.md §4 — never fabricate a metric).
        out[run_id] = sum(graded) / len(graded) if graded else None
    return out


def _snapshot(session: Session, experiment_id: str) -> dict[str, Any]:
    combos = session.scalars(
        select(ExperimentCombination).where(ExperimentCombination.experiment_id == experiment_id)
    ).all()
    by_combo = {c.id: c for c in combos}
    runs = (
        session.scalars(
            select(BenchmarkRun).where(BenchmarkRun.combination_id.in_(list(by_combo)))
        ).all()
        if by_combo
        else []
    )
    states = [r.state for r in runs]
    scores = _scores_from_verdicts(session, [r.id for r in runs])
    rows = []
    for run in runs:
        combo = by_combo[run.combination_id]
        usage = (run.result or {}).get("usage") or {}
        rows.append(
            {
                "run_id": run.id,
                "harness": combo.harness,
                "model_id": combo.model_id,
                "repetition": run.repetition,
                "state": run.state,
                "error_category": run.error_category,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "elapsed_s": (
                    (
                        (run.completed_at or datetime.now(UTC)).replace(tzinfo=UTC)
                        - run.started_at.replace(tzinfo=UTC)
                    ).total_seconds()
                    if run.started_at
                    else None
                ),
                "model_requests": usage.get("requests"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "rate_limited": usage.get("rate_limited", False),
                "budget_exhausted": usage.get("budget_exhausted", False),
                # From the verdict rows, not run.result["score"] — see
                # _scores_from_verdicts.
                "score": scores.get(run.id),
                "patch_produced": (run.result or {}).get("patch_produced"),
            }
        )
    done = sum(1 for s in states if s in TERMINAL)
    return {
        "experiment_id": experiment_id,
        "total": len(runs),
        "done": done,
        "by_state": {s: states.count(s) for s in sorted(set(states))},
        "finished": bool(runs) and done == len(runs),
        "runs": rows,
    }


@router.get("/experiments/{experiment_id}/events")
async def experiment_events(experiment_id: str) -> StreamingResponse:
    """Server-sent stream of run-state snapshots plus individual run events."""
    with SessionLocal() as session:
        if session.get(Experiment, experiment_id) is None:
            raise HTTPException(404, "experiment not found")

    async def stream() -> AsyncIterator[str]:
        seen_events: set[str] = set()
        last_snapshot: str | None = None
        # Guard against an unbounded stream if a run wedges: the browser can
        # always reconnect and replay, since events are persisted.
        for _ in range(60 * 60):
            with SessionLocal() as session:
                snapshot = _snapshot(session, experiment_id)
                combos = session.scalars(
                    select(ExperimentCombination.id).where(
                        ExperimentCombination.experiment_id == experiment_id
                    )
                ).all()
                run_ids = (
                    session.scalars(
                        select(BenchmarkRun.id).where(BenchmarkRun.combination_id.in_(list(combos)))
                    ).all()
                    if combos
                    else []
                )
                events = (
                    session.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id.in_(list(run_ids)))
                        .order_by(RunEvent.created_at)
                    ).all()
                    if run_ids
                    else []
                )
                fresh = [e for e in events if e.id not in seen_events]

            for event in fresh:
                seen_events.add(event.id)
                payload = {
                    "run_id": event.run_id,
                    "type": event.event_type,
                    "payload": event.payload,
                    "at": event.created_at.isoformat(),
                }
                yield f"event: run\ndata: {json.dumps(payload)}\n\n"

            body = json.dumps(snapshot)
            if body != last_snapshot:
                last_snapshot = body
                yield f"event: progress\ndata: {body}\n\n"

            if snapshot["finished"]:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(POLL_INTERVAL_S)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/experiments/{experiment_id}/progress")
def experiment_progress(
    experiment_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Same shape as the SSE `progress` event, for a plain poll or first paint."""
    if session.get(Experiment, experiment_id) is None:
        raise HTTPException(404, "experiment not found")
    return _snapshot(session, experiment_id)


@router.get("/runs/{run_id}/detail")
def run_detail(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    combo = session.get(ExperimentCombination, run.combination_id)
    task = session.get(BenchmarkTask, combo.task_id) if combo else None

    # A run answers every task that shared its snapshot, judging the SAME answer
    # against each rubric — one verdict per task, not one per run. Newest per
    # task, the same rule results_api uses, so the two surfaces cannot disagree.
    # Plain ascending order would be wrong for a different reason: a
    # re-evaluation writes a second row for the same task, and the older one is
    # not the answer anybody wants.
    group_task_ids: list[str] = list(combo.task_ids or []) if combo else []
    if combo and not group_task_ids:
        group_task_ids = [combo.task_id]
    latest: dict[str | None, EvaluationResult] = {}
    for ev in session.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
        .order_by(EvaluationResult.created_at.desc())
    ).all():
        latest.setdefault(ev.task_id, ev)
    titles = (
        {
            t.id: t.title
            for t in session.scalars(
                select(BenchmarkTask).where(BenchmarkTask.id.in_(group_task_ids))
            ).all()
        }
        if group_task_ids
        else {}
    )
    # Group order, so the first entry is the one the run summary scored with
    # (`verdicts[0]`). Rows whose task_id predates per-task evaluation carry
    # None and are appended rather than dropped.
    ordered = [latest[tid] for tid in group_task_ids if tid in latest]
    ordered += [ev for tid, ev in latest.items() if tid not in group_task_ids]
    evaluation = ordered[0] if ordered else None
    metrics = session.scalars(
        select(ModelRequestMetric)
        .where(ModelRequestMetric.run_id == run_id)
        .order_by(ModelRequestMetric.created_at)
    ).all()
    events = session.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.created_at)
    ).all()
    artifact = session.scalars(
        select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == "patch")
    ).first()

    result = run.result or {}
    return {
        "id": run.id,
        "state": run.state,
        "repetition": run.repetition,
        "harness": combo.harness if combo else None,
        "model_id": combo.model_id if combo else None,
        "task": (
            {"id": task.id, "title": task.title, "prompt": task.prompt, "kind": task.kind}
            if task
            else None
        ),
        "error_category": run.error_category,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "result": result,
        "usage": result.get("usage") or {},
        # Kept for callers that only ever wanted one verdict; it is now the
        # group's FIRST task rather than whichever row was written last, which
        # is what the run's own score was taken from.
        "evaluation": (
            {"signal": evaluation.signal, "score": evaluation.score, "results": evaluation.results}
            if evaluation
            else None
        ),
        "evaluations": [
            {
                "task_id": ev.task_id,
                "task_title": titles.get(ev.task_id or "") or (task.title if task else None),
                "signal": ev.signal,
                "score": ev.score,
                "results": ev.results,
            }
            for ev in ordered
        ],
        "model_requests": [
            {
                "http_status": m.http_status,
                "latency_ms": m.latency_ms,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "is_estimated": m.is_estimated,
                "routed_provider": (m.raw_meta or {}).get("routed_provider"),
                "error": (m.raw_meta or {}).get("error"),
            }
            for m in metrics
        ],
        "timeline": [
            {"type": e.event_type, "payload": e.payload, "at": e.created_at.isoformat()}
            for e in events
        ],
        "has_patch": artifact is not None,
    }


@router.get("/runs/{run_id}/patch")
def run_patch(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    artifact = session.scalars(
        select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == "patch")
    ).first()
    if artifact is None:
        raise HTTPException(404, "no patch for this run")
    path = Path(artifact.path)
    if not path.is_file():
        raise HTTPException(410, "patch artifact missing from disk")
    return {"run_id": run_id, "checksum": artifact.checksum, "patch": path.read_text()}
