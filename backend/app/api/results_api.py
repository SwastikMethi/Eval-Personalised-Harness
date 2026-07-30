from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import (
    BenchmarkRun,
    EvaluationResult,
    Experiment,
    ExperimentCombination,
)
from app.scoring.aggregate import (
    RunSample,
    aggregate_combination,
    pareto_frontier,
    recommend,
    score_combinations,
)

router = APIRouter()


def _samples(session: Session, experiment_id: str) -> list[RunSample]:
    combos = session.scalars(
        select(ExperimentCombination).where(
            ExperimentCombination.experiment_id == experiment_id
        )
    ).all()
    samples: list[RunSample] = []
    for combo in combos:
        runs = session.scalars(
            select(BenchmarkRun).where(BenchmarkRun.combination_id == combo.id)
        ).all()
        for run in runs:
            evaluation = session.scalars(
                select(EvaluationResult)
                .where(EvaluationResult.run_id == run.id)
                .order_by(EvaluationResult.created_at.desc())
            ).first()
            duration = None
            if run.started_at and run.completed_at:
                duration = (run.completed_at - run.started_at).total_seconds()
            result = run.result or {}
            tokens = (result.get("input_tokens") or 0) + (result.get("output_tokens") or 0)
            samples.append(
                RunSample(
                    combination_id=combo.id,
                    harness=combo.harness,
                    model_id=combo.model_id,
                    task_id=combo.task_id,
                    state=run.state,
                    score=evaluation.score if evaluation else result.get("score"),
                    signal=evaluation.signal if evaluation else result.get("evaluation_signal"),
                    duration_s=duration,
                    total_tokens=tokens or None,
                    patch_produced=bool(result.get("patch_produced")),
                )
            )
    return samples


@router.get("/experiments/{experiment_id}/results")
def experiment_results(
    experiment_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    if session.get(Experiment, experiment_id) is None:
        raise HTTPException(404, "experiment not found")
    samples = _samples(session, experiment_id)
    if not samples:
        return {"combinations": [], "recommendations": {}, "pareto": {}}

    grouped: dict[str, list[RunSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.combination_id, []).append(sample)
    stats = [aggregate_combination(group) for group in grouped.values()]
    score_combinations(stats)
    recommendations = recommend(stats)

    token_points = [
        (s.combination_id, s.mean_score or 0.0, s.mean_tokens or 0.0)
        for s in stats
        if s.eligible
    ]
    duration_points = [
        (s.combination_id, s.mean_score or 0.0, s.mean_duration_s or 0.0)
        for s in stats
        if s.eligible
    ]
    return {
        "combinations": [vars(s) for s in stats],
        "recommendations": recommendations.get("recommendations", {}),
        "per_combo": recommendations.get("combinations", {}),
        "pareto": {
            "correctness_vs_tokens": pareto_frontier(token_points),
            "correctness_vs_duration": pareto_frontier(duration_points),
        },
        "caveats": [
            "efficiency scores are cohort-relative within each task",
            "results from fewer than 3 completed repetitions are statistically weak",
        ],
    }
