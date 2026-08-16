"""What the results page is allowed to claim.

Every test here is a claim the harness made that was not true, on a real run:

  - it named `best_quality: mini-swe-agent` when both combinations scored 0.0;
  - it said "up to 2 runs executing in parallel" about a strictly serial matrix,
    and the generated summary then repeated it;
  - it showed `execution_efficiency: 0.00` for two combinations differing 2.5x
    in tokens, which reads as "no difference" and is not.

The instruction these enforce is CLAUDE.md §4: do not produce a winner from weak
evaluation signal, and do not state what was not measured.
"""

from datetime import UTC, datetime, timedelta

from app.api.results_api import _gated_efficiency_caveat, _peak_overlap
from app.scoring.aggregate import (
    TIE_EPSILON,
    CombinationStats,
    RunSample,
    aggregate_combination,
    recommend,
    score_combinations,
)


def combo(harness: str, score: float, *, tokens: float = 1000.0) -> CombinationStats:
    samples = [
        RunSample(
            combination_id=f"c-{harness}",
            harness=harness,
            model_id="openai/gpt-oss-120b",
            task_id="t1",
            state="COMPLETED",
            score=score,
            signal="ok",
            duration_s=70.0,
            total_tokens=int(tokens),
            patch_produced=True,
        )
    ]
    return aggregate_combination(samples)


def recommendations_for(*stats: CombinationStats) -> dict:
    ranked = list(stats)
    score_combinations(ranked)
    return recommend(ranked)["recommendations"]


# --- no winner from nothing --------------------------------------------------


def test_two_combinations_at_zero_produce_no_winner() -> None:
    """The exact shape of the real run: both scored 0/7 and one was crowned."""
    recs = recommendations_for(combo("mini-swe-agent", 0.0), combo("smolagents", 0.0))
    quality = recs["best_quality"]

    assert quality["tied"] is True
    assert "above zero" in quality["why"]
    assert "highest" not in quality["why"]


def test_scores_too_close_to_separate_are_a_tie() -> None:
    """Judged scores are noisy — gpt-5.x cannot be pinned to temperature 0 — so
    a hair of difference is sampling, not quality."""
    recs = recommendations_for(
        combo("mini-swe-agent", 0.60), combo("smolagents", 0.60 + TIE_EPSILON / 2)
    )
    assert recs["best_quality"]["tied"] is True
    assert "too close to separate" in recs["best_quality"]["why"]


def test_a_real_gap_still_names_a_winner() -> None:
    """The guard must not refuse to answer when the data does separate them."""
    recs = recommendations_for(combo("mini-swe-agent", 0.29), combo("smolagents", 0.86))
    quality = recs["best_quality"]

    assert quality["tied"] is False
    assert quality["harness"] == "smolagents"
    assert "highest correctness" in quality["why"]


# --- overlap is measured, not counted ---------------------------------------


def base(minute: int) -> datetime:
    return datetime(2026, 8, 15, 12, minute, tzinfo=UTC)


def test_serial_runs_report_no_overlap() -> None:
    """69s then 86s, back to back. The old counter called this 2 in parallel
    because a finishing run's task lingers in the active dict."""
    assert _peak_overlap([(base(0), base(5)), (base(5), base(10))]) == 1


def test_genuinely_overlapping_runs_are_detected() -> None:
    assert _peak_overlap([(base(0), base(10)), (base(5), base(15))]) == 2


def test_three_at_once_counts_three() -> None:
    assert (
        _peak_overlap([(base(0), base(30)), (base(5), base(20)), (base(10), base(15))]) == 3
    )


def test_a_run_ending_exactly_as_another_starts_did_not_overlap_it() -> None:
    end = base(0) + timedelta(seconds=90)
    assert _peak_overlap([(base(0), end), (end, end + timedelta(seconds=90))]) == 1


def test_no_finished_runs_is_not_an_overlap() -> None:
    assert _peak_overlap([]) == 0


# --- a gated zero is not a measurement --------------------------------------


def test_all_zero_correctness_explains_the_efficiency_gate() -> None:
    caveats = _gated_efficiency_caveat(
        [combo("mini-swe-agent", 0.0, tokens=7028), combo("smolagents", 0.0, tokens=17766)]
    )
    assert caveats and "gated behind correctness" in caveats[0]
    assert "avg_tokens" in caveats[0]


def test_the_gate_explanation_stays_quiet_when_something_scored() -> None:
    """It is only confusing when the zero is the gate rather than the result."""
    assert _gated_efficiency_caveat([combo("a", 0.0), combo("b", 0.7)]) == []
