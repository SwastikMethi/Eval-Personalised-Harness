"""A spent-budget failure must describe what was measured.

The message was a constant blaming "a terminal 429 retried instead of stopping".
That was true of the incident that prompted it and of nothing since: a live
2-harness run ended with 8 of 8 requests succeeding and `rate_limited` false,
and the message sent its reader hunting a rate-limit problem that did not exist.
Asserting an unmeasured cause is the same class of error as a fabricated metric.
"""

from app.orchestration.queue import budget_failure_message

CLEAN = {
    "requests": 8,
    "succeeded": 8,
    "failed_requests": 0,
    "rate_limited": False,
    "input_tokens": 40610,
    "output_tokens": 4085,
}


def test_a_budget_spent_on_successful_calls_does_not_mention_rate_limiting() -> None:
    message = budget_failure_message(CLEAN)
    assert "429" not in message
    assert "retrying" not in message
    assert "all 8 requests" in message
    assert "40610" in message and "4085" in message


def test_a_genuine_retry_storm_is_still_named_as_one() -> None:
    message = budget_failure_message({**CLEAN, "failed_requests": 6, "succeeded": 2})
    assert "6 of 8" in message
    assert "kept retrying" in message


def test_rate_limiting_alone_is_enough_to_name_it() -> None:
    """A throttled run can still report every request as eventually succeeding;
    the flag is the signal, not the failure count."""
    message = budget_failure_message({**CLEAN, "rate_limited": True})
    assert "kept retrying" in message


def test_missing_counters_do_not_crash_the_message() -> None:
    """The usage record comes from the proxy and a field can be absent; a run
    must not fail to record WHY it failed."""
    assert "budget spent" in budget_failure_message({})
