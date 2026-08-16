"""Letting an agent run until it finishes, without losing the result.

Removing the request cap sounds like a one-line change and is not. Two rules in
`aggregate.py` veto a combination whose runs end in TIMED_OUT — `timeout_rate >
0.5` and `completed == 0` — so once runs stop hitting a request ceiling and
start hitting the clock, every combination becomes ineligible and the benchmark
produces no ranking at all, however good the patches were.

So an uncapped run needs three things, tested here:
  1. a timeout that produced a patch is a RESULT, graded, not a failure;
  2. a timeout that produced nothing is still a failure;
  3. something other than a request count bounds the spend, because 100 requests
     cost anywhere from 100k to 3.0M input tokens depending on context growth.
"""

import pytest

from app.api.proxy import _authorize, issue_run_token, revoke_run_token, run_usage
from app.scoring.aggregate import RunSample, aggregate_combination


def sample(state: str, *, patch: bool = True, score: float | None = 0.8) -> RunSample:
    return RunSample(
        combination_id="c1",
        harness="mini-swe-agent",
        model_id="openai/gpt-oss-120b",
        task_id="t1",
        state=state,
        patch_produced=patch,
        score=score,
        signal="ok",
        duration_s=1700.0,
        total_tokens=3_000_000,
    )


# --- eligibility ------------------------------------------------------------


def test_a_long_run_that_produced_a_patch_stays_in_the_ranking() -> None:
    """The whole point. A run graded COMPLETED after going the distance must not
    be vetoed for having taken the distance — slowness belongs in
    execution_efficiency, which is already 15% of the weighted score."""
    stats = aggregate_combination([sample("COMPLETED")])
    assert stats.eligible, stats.ineligible_reasons
    assert stats.timeout_rate == 0.0


def test_runs_that_only_ever_time_out_are_still_excluded() -> None:
    """Guards the rule we are working around, so nobody later 'simplifies' it
    away: a combination that never finishes anything is not a winner."""
    stats = aggregate_combination([sample("TIMED_OUT", patch=False, score=None)])
    assert not stats.eligible
    assert "no completed repetitions" in stats.ineligible_reasons


# --- the proxy's ceilings ---------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_tokens():  # type: ignore[no-untyped-def]
    yield
    for run_id in ("uncapped-run", "capped-run", "token-run"):
        revoke_run_token(run_id)


def test_an_uncapped_run_is_not_stopped_by_a_request_count() -> None:
    token = issue_run_token("uncapped-run", "m1", max_requests=None)
    for _ in range(200):
        _authorize(f"Bearer {token}", "m1")
    assert run_usage("uncapped-run")["requests"] == 200
    assert run_usage("uncapped-run")["budget_exhausted"] is False


def test_a_capped_run_still_stops() -> None:
    """Absent config keeps the old behaviour; only an explicit null lifts it."""
    token = issue_run_token("capped-run", "m1", max_requests=3)
    for _ in range(3):
        _authorize(f"Bearer {token}", "m1")
    with pytest.raises(Exception, match="request budget exceeded"):
        _authorize(f"Bearer {token}", "m1")


def test_the_token_ceiling_stops_a_run_the_request_count_would_not() -> None:
    """The replacement guard. Requests are a poor meter for spend: a measured
    run cost 3.0M input tokens across 100 calls because every call resends the
    whole conversation."""
    token = issue_run_token("token-run", "m1", max_requests=None, max_input_tokens=1000)
    entry = _authorize(f"Bearer {token}", "m1")
    entry.input_tokens = 1200  # as the proxy would record after a fat call

    with pytest.raises(Exception, match="input-token budget exceeded"):
        _authorize(f"Bearer {token}", "m1")
    assert run_usage("token-run")["budget_exhausted"] is True
