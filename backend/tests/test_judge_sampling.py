"""Grading takes the median of several samples, and shows the spread.

The judge cannot be made deterministic: the gpt-5 family fixes sampling at
temperature 1 and rejects an explicit value (providers/openai_api.py). It also
has a tail — one measured answer scored 0.25 having judged 2 of 6 criteria,
then 0.83 judging 5 of 6 on thirteen consecutive re-runs of identical input,
across two different token budgets. The cause was never found, which is exactly
why a single draw must not decide a grade.
"""

from typing import Any

import pytest

from app.core.config import settings
from app.db.engine import SessionLocal
from app.evaluators import judge as judge_mod
from app.models import (
    BenchmarkRun,
    BenchmarkTask,
    EvaluationResult,
    Experiment,
    ExperimentCombination,
    Repository,
)
from app.models.core import RunState
from app.orchestration.queue import QueueWorker
from app.repositories import analyzer as analyzer_mod
from app.tasks import propose

RUBRIC = [
    {"criterion": f"criterion {i}", "evidence": "src/server.py", "depth": "structural"}
    for i in range(6)
]


def _theory_run() -> tuple[str, str]:
    with SessionLocal() as session:
        repo = Repository(name="js", source="local", path_or_url="/tmp/js-does-not-exist")
        session.add(repo)
        session.flush()
        task = BenchmarkTask(repository_id=repo.id, kind="theory", title="q", prompt="explain")
        exp = Experiment(repository_id=repo.id, name="js")
        session.add_all([task, exp])
        session.flush()
        combo = ExperimentCombination(
            experiment_id=exp.id, task_id=task.id, task_ids=[task.id],
            harness="fake", provider="fake", model_id="fake/deterministic-1:free",
        )
        session.add(combo)
        session.flush()
        run = BenchmarkRun(
            combination_id=combo.id, repetition=1, state=RunState.RUNNING,
            idempotency_key=f"{combo.id}:1",
        )
        session.add(run)
        session.commit()
        propose.save_task_meta(task.id, {"rubric": RUBRIC})
        return run.id, task.id


def _stub_analyzer(monkeypatch: pytest.MonkeyPatch, scores: list[float]) -> dict[str, int]:
    """Serve `scores` in order, one per judge_answer call."""
    calls = {"n": 0}

    class _Analyzer:
        provider = object()
        provenance = {"provider": "openai", "model": "gpt-5.6-sol"}

    monkeypatch.setattr(analyzer_mod, "select_analyzer", lambda *_a, **_k: _Analyzer())

    async def _resolve(_analyzer: Any) -> str:
        return "gpt-5.6-sol"

    monkeypatch.setattr(analyzer_mod, "resolve_model", _resolve)

    async def _judge_answer(*_a: Any, **_k: Any) -> judge_mod.Verdict:
        score = scores[min(calls["n"], len(scores) - 1)]
        calls["n"] += 1
        return judge_mod.Verdict(
            score=score, met=[f"met at {score}"], missing=[], rationale=f"sample {calls['n']}"
        )

    monkeypatch.setattr(judge_mod, "judge_answer", _judge_answer)
    return calls


def _stored(run_id: str) -> EvaluationResult:
    with SessionLocal() as session:
        row = session.query(EvaluationResult).filter_by(run_id=run_id).one()
        session.expunge(row)
        return row


async def test_a_lone_outlier_does_not_decide_the_grade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured failure: 0.25 once, 0.83 otherwise. The median discards it.

    A mean would report 0.64 — a number no judge returned and which understates
    an answer that five graders in a row scored 0.83.
    """
    monkeypatch.setattr(settings, "judge_samples", 3)
    run_id, task_id = _theory_run()
    calls = _stub_analyzer(monkeypatch, [0.25, 0.8333, 0.8333])

    await QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")._judge(
        run_id, task_id, None, "an answer"
    )

    assert calls["n"] == 3, "graded once per sample"
    row = _stored(run_id)
    assert row.score == pytest.approx(0.8333), "the median, not the outlier and not the mean"
    assert row.results["judge_samples"] == pytest.approx([0.25, 0.8333, 0.8333])
    # The spread has to be visible: a grade that ranged this far is not a fact.
    assert row.results["judge_spread"] == pytest.approx(0.5833, abs=1e-3)


async def test_the_reported_breakdown_belongs_to_the_reported_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The median VERDICT is kept, not a median score bolted to another verdict."""
    monkeypatch.setattr(settings, "judge_samples", 3)
    run_id, task_id = _theory_run()
    _stub_analyzer(monkeypatch, [0.1, 0.5, 0.9])

    await QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")._judge(
        run_id, task_id, None, "an answer"
    )

    row = _stored(run_id)
    assert row.score == pytest.approx(0.5)
    assert row.results["judge"]["met"] == ["met at 0.5"], "breakdown matches the score shown"


async def test_one_sample_is_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """JUDGE_SAMPLES=1 opts out; the spread is then zero, not absent."""
    monkeypatch.setattr(settings, "judge_samples", 1)
    run_id, task_id = _theory_run()
    calls = _stub_analyzer(monkeypatch, [0.42])

    await QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")._judge(
        run_id, task_id, None, "an answer"
    )

    assert calls["n"] == 1
    row = _stored(run_id)
    assert row.score == pytest.approx(0.42)
    assert row.results["judge_spread"] == 0.0


async def test_what_produced_the_verdict_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the product and a re-run disagreed by 0.58, nothing persisted could
    separate "different inputs" from "different answer to identical inputs"."""
    monkeypatch.setattr(settings, "judge_samples", 1)
    run_id, task_id = _theory_run()
    _stub_analyzer(monkeypatch, [0.5])

    await QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")._judge(
        run_id, task_id, None, "an answer of known length"
    )

    inputs = _stored(run_id).results["judge_inputs"]
    assert inputs["model"] == "gpt-5.6-sol"
    assert inputs["answer_chars"] == len("an answer of known length")
    assert inputs["rubric_criteria"] == 6
