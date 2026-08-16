"""mini-swe-agent must not report an unread trajectory as zero steps.

A real run recorded agent_steps=0 while the proxy's metric rows proved it had
called the model and received a 200 — an agent that made a model call did not
take zero steps. `cat` of a missing path yields empty stdout, which parses the
same as corrupt JSON, so a missing measurement was being published as a
measured zero (§4: mark unavailable metrics null).
"""

import json

from app.harnesses.mini_swe_agent import MiniSweAgentHarness

parse = MiniSweAgentHarness._parse_trajectory


def test_missing_trajectory_is_unknown_not_zero() -> None:
    for raw in ("", "   ", "not json at all", "{"):
        steps, requests, commands, final = parse(raw)
        assert steps is None, f"{raw!r} must not report a step count"
        assert requests is None
        assert commands is None
        assert final is None


def test_real_trajectory_is_counted() -> None:
    raw = json.dumps(
        {
            "messages": [
                {"role": "system", "content": "you are an agent"},
                {"role": "user", "content": "do the task"},
                {"role": "assistant", "content": "step 1"},
                {"role": "user", "content": "observation"},
                {"role": "assistant", "content": "step 2 done"},
            ]
        }
    )
    steps, requests, commands, final = parse(raw)
    assert steps == 2
    assert requests == 2
    assert commands == 1  # user turns after the initial task prompt
    assert final == "step 2 done"


def test_zero_steps_is_still_reportable_when_the_trajectory_is_readable() -> None:
    """An agent that genuinely did nothing but wrote a trajectory reports 0 —
    the None is reserved for 'could not read', so the two stay distinguishable.
    """
    steps, requests, commands, final = parse(json.dumps({"messages": []}))
    assert steps == 0
    assert requests == 0
    assert commands == 0
    assert final is None
