from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import (
    BenchmarkRun,
    BenchmarkTask,
    EvaluationResult,
    Experiment,
    ExperimentCombination,
)
from app.providers.openrouter import ProviderError
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
        select(ExperimentCombination).where(ExperimentCombination.experiment_id == experiment_id)
    ).all()
    # Task kinds for every task any combination covers, fetched once rather
    # than per run: eligibility judges a patch or a graded answer depending on
    # what the task actually asked for.
    task_ids = {t for c in combos for t in (list(c.task_ids or []) or [c.task_id])}
    kinds: dict[str, str] = (
        {
            t.id: t.kind
            for t in session.scalars(
                select(BenchmarkTask).where(BenchmarkTask.id.in_(task_ids))
            ).all()
        }
        if task_ids
        else {}
    )

    samples: list[RunSample] = []
    for combo in combos:
        runs = session.scalars(
            select(BenchmarkRun).where(BenchmarkRun.combination_id == combo.id)
        ).all()
        for run in runs:
            # A run may answer several tasks that shared its snapshot, writing
            # one evaluation each. Taking only the newest dropped every task but
            # one and filed its score under the group's first task.
            evaluations = list(
                session.scalars(
                    select(EvaluationResult)
                    .where(EvaluationResult.run_id == run.id)
                    .order_by(EvaluationResult.created_at.desc())
                ).all()
            )
            # Newest per task, so a re-evaluation supersedes rather than doubles.
            latest: dict[str | None, EvaluationResult] = {}
            for ev in evaluations:
                latest.setdefault(ev.task_id, ev)
            duration = None
            if run.started_at and run.completed_at:
                duration = (run.completed_at - run.started_at).total_seconds()
            result = run.result or {}
            # Prefer the PROXY's usage: it is recorded identically for every
            # harness. Harness self-reporting is not comparable — smolagents
            # reports usage and mini-SWE-agent legitimately does not, so using
            # it would compare a harness that counts against one that doesn't,
            # in a product whose whole purpose is comparing harnesses.
            usage = result.get("usage") or {}
            tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            if not tokens:
                tokens = (result.get("input_tokens") or 0) + (result.get("output_tokens") or 0)
            # Cost is per RUN, so a run answering several tasks must not report
            # its full duration and tokens against each of them — that would
            # make a grouped run look several times more expensive than it was
            # and distort efficiency, which is normalised within a task.
            # Sharing it evenly keeps the totals right and the per-task figure
            # honest: two answers in 500s averaged 250s each.
            per_task = max(len(latest) or len(combo.task_ids or [combo.task_id]), 1)
            share = (duration / per_task) if duration is not None else None
            token_share = (tokens // per_task) if tokens else 0

            graded: list[tuple[str | None, EvaluationResult | None]] = (
                list(latest.items()) if latest else [(combo.task_id, None)]
            )
            for task_id, evaluation in graded:
                samples.append(
                    RunSample(
                        combination_id=combo.id,
                        harness=combo.harness,
                        model_id=combo.model_id,
                        task_id=task_id or combo.task_id,
                        state=run.state,
                        score=evaluation.score if evaluation else result.get("score"),
                        signal=(
                            evaluation.signal if evaluation else result.get("evaluation_signal")
                        ),
                        duration_s=share,
                        total_tokens=token_share or None,
                        patch_produced=bool(result.get("patch_produced")),
                        # Eligibility asks for the right deliverable per kind:
                        # a patch for a replay, a graded answer for a
                        # comprehension task.
                        task_kind=kinds.get(task_id or combo.task_id, "commit"),
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
        (s.combination_id, s.mean_score or 0.0, s.mean_tokens or 0.0) for s in stats if s.eligible
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
            "resource efficiency currently mirrors execution efficiency — container "
            "CPU/memory is collected but not yet persisted, so its 5% weight adds "
            "no independent signal",
            *_parallel_caveat(session, experiment_id),
            *_judged_caveat(session, experiment_id),
            *_gated_efficiency_caveat(stats),
        ],
    }


def _judged_caveat(session: Session, experiment_id: str) -> list[str]:
    """Warn when scores came from a judge rather than from execution.

    gpt-5.x rejects temperature=0 (Known Defect #17), so the judge is not
    deterministic: the same answer can score differently on two passes. That is
    not a reason to distrust the ranking, but it IS a reason to want more than
    one repetition before believing a small gap between two combinations.
    """
    judged = session.scalars(
        select(EvaluationResult.results)
        .join(BenchmarkRun, BenchmarkRun.id == EvaluationResult.run_id)
        .join(ExperimentCombination, ExperimentCombination.id == BenchmarkRun.combination_id)
        .where(ExperimentCombination.experiment_id == experiment_id)
    ).all()
    if not any(isinstance(r, dict) and "judge" in r for r in judged):
        return []
    return [
        "correctness here was awarded by a model against a fixed rubric, not by running "
        "tests. The judge cannot be pinned to temperature 0, so repeat the matrix and "
        "compare distributions — treat combinations within one rubric criterion of each "
        "other as tied rather than ranked"
    ]


SUMMARY_SYSTEM = """You write the closing summary of a benchmark comparing coding-agent stacks.

You are given per-combination statistics and, where the tasks were graded by
rubric, the per-run verdicts.

Write 4-8 sentences of plain prose. Rules:
- Name which combination performed better and on what evidence. If the evidence
  does not separate them, say they are tied — that is a finding, not a failure.
- Quote the numbers you rely on.
- Correctness, reliability and efficiency can disagree. Say so when they do
  rather than averaging them into a verdict the data does not support.
- Anything marked statistically weak, or scored by a judge, is provisional. Say
  which parts of your conclusion rest on it.
- Never invent a number that is not in the input."""


@router.post("/experiments/{experiment_id}/summary")
async def experiment_summary(
    experiment_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """A written comparison of how the combinations actually did.

    Deliberately a POST and deliberately not automatic: it costs a model call,
    and a summary regenerated on every page load would be both expensive and
    subtly different each time.
    """
    import json

    from app.core.config import settings as cfg
    from app.repositories import analyzer as analyzer_mod

    results = experiment_results(experiment_id, session)
    if not results.get("combinations"):
        return {"summary": "", "note": "no completed runs to summarise"}

    try:
        analyzer = analyzer_mod.select_analyzer(cfg)
        model_id = await analyzer_mod.resolve_model(analyzer)
    except analyzer_mod.AnalyzerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc

    verdicts = session.scalars(
        select(EvaluationResult.results)
        .join(BenchmarkRun, BenchmarkRun.id == EvaluationResult.run_id)
        .join(ExperimentCombination, ExperimentCombination.id == BenchmarkRun.combination_id)
        .where(ExperimentCombination.experiment_id == experiment_id)
    ).all()
    judged = [r.get("judge") for r in verdicts if isinstance(r, dict) and r.get("judge")]

    payload = {
        "combinations": results["combinations"],
        "recommendations": results["recommendations"],
        "caveats": results["caveats"],
        "judge_verdicts": judged[:20],
    }
    try:
        completion = await analyzer.provider.complete(
            model_id,
            [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": json.dumps(payload, default=str)[:24000]},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc

    return {
        "summary": (completion.content or "").strip(),
        "provenance": analyzer.provenance,
        "caveats": results["caveats"],
    }


def _peak_overlap(windows: list[tuple[Any, Any]]) -> int:
    """The most runs alive at any one instant, by a sweep over start/end events.

    A run that ends at exactly the moment another begins did not overlap it, so
    ends are processed before starts at the same timestamp — which is the whole
    difference between "serial" and the false "2 in parallel" this replaces.
    """
    events: list[tuple[Any, int]] = []
    for start, end in windows:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda e: (e[0], e[1]))

    peak = live = 0
    for _, delta in events:
        live += delta
        peak = max(peak, live)
    return peak


def _gated_efficiency_caveat(stats: list[Any]) -> list[str]:
    """Explain a 0.0 efficiency that is a gate, not a measurement.

    Efficiency is multiplied by a correctness gate so a fast wrong answer cannot
    rank — a locked invariant, unchanged here. But when nothing scored, every
    efficiency component reads 0.0 and that looks like "no difference between
    them", which was false by 2.5x on tokens the first time it happened.
    """
    eligible = [s for s in stats if s.eligible]
    if not eligible or any((s.mean_score or 0.0) > 0.0 for s in eligible):
        return []
    return [
        "every efficiency component reads 0.00 because efficiency is gated behind "
        "correctness, and nothing scored — this is the gate firing, not the "
        "combinations performing identically. Compare avg_tokens and avg_duration_s "
        "directly instead"
    ]


def _parallel_caveat(session: Session, experiment_id: str) -> list[str]:
    """Say so when durations were measured against competing runs.

    Named precisely: parallel runs share CPU, so only DURATION-derived numbers
    (execution efficiency, 15% of the score) become less comparable. Correctness,
    reliability and token counts are unaffected, and a caveat implying otherwise
    would cast false doubt on the scores it describes.
    """
    combos = session.scalars(
        select(ExperimentCombination.id).where(ExperimentCombination.experiment_id == experiment_id)
    ).all()
    if not combos:
        return []
    runs = session.scalars(
        select(BenchmarkRun).where(BenchmarkRun.combination_id.in_(list(combos)))
    ).all()

    # Derived from when runs actually ran, not from the recorded `concurrency`
    # counter. That counter is `len(self._active)`, and a finishing run's task
    # lingers in that dict until its done-callback fires — so a strictly serial
    # matrix reported "2 runs in parallel", and the generated summary repeated
    # the claim back to the user. Timestamps cannot race in that way.
    windows = [
        (r.started_at, r.completed_at)
        for r in runs
        if r.started_at is not None and r.completed_at is not None
    ]
    peak = _peak_overlap(windows)
    if peak <= 1:
        return []
    return [
        f"durations were measured with up to {peak} runs executing in parallel, so "
        "execution-efficiency comparisons are less reliable than a serial matrix; "
        "correctness, reliability and token counts are unaffected"
    ]
