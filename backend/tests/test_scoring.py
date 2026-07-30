from app.scoring.aggregate import (
    RunSample,
    aggregate_combination,
    pareto_frontier,
    recommend,
    score_combinations,
)


def sample(
    combo: str = "c1",
    state: str = "COMPLETED",
    score: float | None = 1.0,
    duration: float | None = 10.0,
    tokens: int | None = 100,
    patch: bool = True,
    signal: str | None = "ok",
    harness: str = "h",
    model: str = "m",
    task: str = "t1",
) -> RunSample:
    return RunSample(
        combination_id=combo,
        harness=harness,
        model_id=model,
        task_id=task,
        state=state,
        score=score,
        signal=signal,
        duration_s=duration,
        total_tokens=tokens,
        patch_produced=patch,
    )


def test_aggregation_basics() -> None:
    stats = aggregate_combination(
        [sample(score=1.0), sample(score=0.5), sample(state="TIMED_OUT", score=None)]
    )
    assert stats.runs == 3
    assert stats.completed == 2
    assert stats.mean_score == 0.75
    assert stats.timeout_rate == 1 / 3
    assert stats.eligible


def test_never_patches_is_ineligible() -> None:
    stats = aggregate_combination([sample(patch=False, score=0.0), sample(patch=False, score=0.0)])
    assert not stats.eligible
    assert "never produces a patch" in stats.ineligible_reasons


def test_majority_timeouts_ineligible() -> None:
    stats = aggregate_combination(
        [sample(state="TIMED_OUT", score=None), sample(state="TIMED_OUT", score=None), sample()]
    )
    assert not stats.eligible


def test_insufficient_signal_blocks_recommendation() -> None:
    stats = aggregate_combination(
        [sample(signal="INSUFFICIENT_EVALUATION_SIGNAL", score=None)]
    )
    assert not stats.eligible


def test_statistically_weak_below_three_reps() -> None:
    weak = aggregate_combination([sample(), sample()])
    strong = aggregate_combination([sample(), sample(), sample()])
    assert weak.statistically_weak
    assert not strong.statistically_weak


def test_fast_but_wrong_never_wins() -> None:
    """A fast incorrect run must not outrank a slower correct one (spec §31)."""
    fast_wrong = aggregate_combination(
        [sample(combo="fw", score=0.0, duration=1.0, tokens=10, harness="fast", model="m1")] * 3
    )
    slow_right = aggregate_combination(
        [sample(combo="sr", score=1.0, duration=100.0, tokens=5000, harness="slow", model="m2")]
        * 3
    )
    stats = [fast_wrong, slow_right]
    score_combinations(stats)
    assert (slow_right.weighted_score or 0) > (fast_wrong.weighted_score or 0)


def test_recommendations_produced() -> None:
    a = aggregate_combination(
        [sample(combo="a", harness="h1", model="m1", score=1.0, duration=50.0)] * 3
    )
    b = aggregate_combination(
        [sample(combo="b", harness="h2", model="m2", score=0.6, duration=5.0)] * 3
    )
    stats = [a, b]
    score_combinations(stats)
    result = recommend(stats)
    recs = result["recommendations"]
    assert recs["best_quality"]["harness"] == "h1"
    assert recs["best_balanced"]["harness"] in ("h1", "h2")
    assert not recs["best_quality"]["statistically_weak"]


def test_ineligible_excluded_from_recommendations() -> None:
    bad = aggregate_combination([sample(combo="x", harness="hx", patch=False, score=0.0)] * 3)
    good = aggregate_combination([sample(combo="y", harness="hy")] * 3)
    stats = [bad, good]
    score_combinations(stats)
    recs = recommend(stats)["recommendations"]
    assert recs["best_quality"]["harness"] == "hy"


def test_pareto_frontier() -> None:
    points = [("a", 1.0, 1000.0), ("b", 0.9, 100.0), ("c", 0.5, 500.0)]
    frontier = pareto_frontier(points)
    assert "a" in frontier  # best correctness
    assert "b" in frontier  # much cheaper, nearly as good
    assert "c" not in frontier  # dominated by b
