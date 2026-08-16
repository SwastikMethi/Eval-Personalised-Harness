"""Grading a comprehension answer, grounded and blind.

The risk this whole file guards against is a number that looks like a
measurement and is not. An LLM asked "how good is this answer, 0 to 10" will
always produce something plausible. So:

  - the score is COUNTED here from rubric hits, never taken from the model;
  - a criterion the model invents cannot be credited, because it is matched
    against the rubric we sent;
  - the judge is never told which harness wrote the answer, since ranking
    harnesses is the entire point;
  - the rubric itself is grounded when proposed — a criterion citing a path
    that does not exist is dropped before it can mark anyone wrong.
"""

import json

import pytest

from app.evaluators.judge import (
    answer_from_patch,
    build_messages,
    parse_verdict,
    resolve_answer,
)
from app.repositories.digest import Digest
from app.repositories.suggest import SuggestionError
from app.tasks.propose import parse_proposals

RUBRIC = [
    {"criterion": "names src/server.py as the entry point", "evidence": "src/server.py"},
    {"criterion": "mentions the on-disk cache under data/cache", "evidence": "data/cache"},
    {"criterion": "describes the PokeAPI fallback on a cache miss", "evidence": "src/utils"},
]


def verdict_json(met: list[bool], invented: list[str] | None = None) -> str:
    return json.dumps({
        "criteria": [
            {"criterion": RUBRIC[i]["criterion"], "met": m, "note": "n"}
            for i, m in enumerate(met)
        ],
        "invented": invented or [],
        "rationale": "covered the entry point, missed the cache",
    })


# --- the score is counted, not asked for ------------------------------------


def test_score_is_the_hit_rate_over_the_rubric_we_sent() -> None:
    v = parse_verdict(verdict_json([True, False, True]), RUBRIC)
    assert v.score == pytest.approx(2 / 3)
    assert len(v.met) == 2
    assert v.missing == ["mentions the on-disk cache under data/cache"]


def test_partial_credit_is_worth_half() -> None:
    """A criterion covering three things, answered right for two, used to score
    zero — indistinguishable from not answering at all."""
    payload = json.dumps({
        "criteria": [
            {"criterion": RUBRIC[0]["criterion"], "verdict": "met"},
            {"criterion": RUBRIC[1]["criterion"], "verdict": "partial"},
            {"criterion": RUBRIC[2]["criterion"], "verdict": "missed"},
        ],
        "invented": [],
    })
    v = parse_verdict(payload, RUBRIC)
    assert v.score == pytest.approx((1 + 0.5) / 3)
    assert v.met == [RUBRIC[0]["criterion"]]
    assert v.partial == [RUBRIC[1]["criterion"]]
    assert v.missing == [RUBRIC[2]["criterion"]]


def test_the_old_met_boolean_still_scores() -> None:
    """A judge that ignores the enum must not silently zero a good answer."""
    payload = json.dumps({
        "criteria": [{"criterion": RUBRIC[0]["criterion"], "met": True}], "invented": []
    })
    assert parse_verdict(payload, RUBRIC).score == pytest.approx(1 / 3)


def test_shallow_honest_and_fabricated_answers_no_longer_score_the_same() -> None:
    """The reason this change exists. Three tasks in a row scored exactly 0.0 —
    a careful answer that named real modules but lacked depth landed on the same
    number as one that invented an architecture. A scale where good and bad are
    indistinguishable is not measuring anything."""
    shallow = parse_verdict(
        json.dumps({"criteria": [
            {"criterion": RUBRIC[0]["criterion"], "verdict": "met"},
            {"criterion": RUBRIC[1]["criterion"], "verdict": "partial"},
            {"criterion": RUBRIC[2]["criterion"], "verdict": "missed"},
        ], "invented": []}), RUBRIC)
    fabricated = parse_verdict(
        json.dumps({"criteria": [
            {"criterion": c["criterion"], "verdict": "missed"} for c in RUBRIC
        ], "invented": ["src/router.py"]}), RUBRIC)

    assert fabricated.score == 0.0
    assert shallow.score is not None and shallow.score > fabricated.score


def test_a_criterion_the_judge_invented_earns_nothing() -> None:
    """Otherwise a judge can add "explains clearly", mark it met, and inflate
    its own score past what the rubric actually asked for."""
    payload = json.dumps({
        "criteria": [
            {"criterion": RUBRIC[0]["criterion"], "met": True},
            {"criterion": "the writing is elegant and well organised", "met": True},
            {"criterion": "deploys to production", "met": True},
        ],
        "invented": [],
        "rationale": "",
    })
    v = parse_verdict(payload, RUBRIC)
    assert v.score == pytest.approx(1 / 3), "only the real criterion counted"
    assert len(v.missing) == 2


def test_a_model_supplied_overall_score_is_ignored() -> None:
    payload = json.dumps({
        "criteria": [{"criterion": RUBRIC[0]["criterion"], "met": True}],
        "score": 0.95,          # the model's own flattering opinion
        "overall": 10,
        "invented": [],
    })
    assert parse_verdict(payload, RUBRIC).score == pytest.approx(1 / 3)


def test_invented_modules_are_carried_through() -> None:
    v = parse_verdict(verdict_json([True, True, True], ["src/router.py"]), RUBRIC)
    assert v.invented == ["src/router.py"]
    assert v.score == 1.0, "inventing is reported separately, not silently scored"


# --- blind -------------------------------------------------------------------


def test_the_judge_is_never_told_who_wrote_the_answer() -> None:
    messages = build_messages(
        "explain the flow",
        RUBRIC,
        "the entry point is src/server.py",
        ["src/server.py", "data/cache"],
    )
    blob = json.dumps(messages).lower()
    for identity in ("mini-swe-agent", "smolagents", "gpt-oss", "harness", "run_id"):
        assert identity not in blob, f"{identity} leaked into the judge prompt"


# --- answer resolution -------------------------------------------------------

PATCH_WITH_ANSWER = (
    "diff --git a/ANSWER.md b/ANSWER.md\n"
    "--- /dev/null\n"
    "+++ b/ANSWER.md\n"
    "@@ -0,0 +1,2 @@\n"
    "+# Architecture\n"
    "+The entry point is src/server.py.\n"
)


def test_answer_md_is_preferred_over_the_final_message() -> None:
    """smolagents truncates final_message at 4000 chars, so the file wins."""
    answer, source = resolve_answer(PATCH_WITH_ANSWER, "a much shorter summary")
    assert source == "ANSWER.md"
    assert "The entry point is src/server.py." in (answer or "")


def test_the_final_message_is_the_fallback() -> None:
    answer, source = resolve_answer("diff --git a/x.py b/x.py\n", "my answer text")
    assert (answer, source) == ("my answer text", "final_message")


def test_no_answer_at_all_is_reported_not_guessed() -> None:
    assert resolve_answer(None, None) == (None, "none")


def test_only_answer_md_is_extracted_from_a_multi_file_patch() -> None:
    patch = PATCH_WITH_ANSWER + (
        "diff --git a/notes.txt b/notes.txt\n"
        "--- /dev/null\n"
        "+++ b/notes.txt\n"
        "@@ -0,0 +1 @@\n"
        "+scratch\n"
    )
    assert "scratch" not in (answer_from_patch(patch) or "")


# --- rubric grounding at proposal time --------------------------------------


def digest_for(paths: list[str]) -> Digest:
    return Digest(tree=paths)


def test_criterion_depth_is_carried_through() -> None:
    """Depth is what lets a low score be read properly: structural-met means
    "skimmed and was honest", all-missed means "did not look"."""
    payload = json.dumps({"tasks": [{
        "category": "architecture", "title": "t", "prompt": "p",
        "rubric": [
            {"criterion": "names the entry point", "depth": "structural",
             "evidence": "src/server.py"},
            {"criterion": "explains the cache miss", "depth": "behavioural",
             "evidence": "src/server.py"},
            {"criterion": "gives the call order", "evidence": "src/server.py"},
        ],
    }]})
    rubric = parse_proposals(payload, digest_for(["src/server.py"]))[0].rubric

    assert [c.depth for c in rubric] == ["structural", "behavioural", "deep"]


def test_an_unknown_depth_falls_back_to_the_hardest() -> None:
    """Assuming the easy tier would flatter the agent for free."""
    payload = json.dumps({"tasks": [{
        "category": "architecture", "title": "t", "prompt": "p",
        "rubric": [{"criterion": "c", "depth": "trivial", "evidence": "src/server.py"}],
    }]})
    assert parse_proposals(payload, digest_for(["src/server.py"]))[0].rubric[0].depth == "deep"


def test_criteria_citing_paths_that_do_not_exist_are_dropped() -> None:
    """A hallucinated rubric would mark every answer wrong with total
    confidence, so it never gets stored in the first place."""
    payload = json.dumps({"tasks": [{
        "category": "architecture",
        "title": "Module map",
        "prompt": "describe the modules",
        "rubric": [
            {"criterion": "names the server module", "evidence": "src/server.py"},
            {"criterion": "names the router", "evidence": "src/router.py"},
        ],
    }]})
    tasks = parse_proposals(payload, digest_for(["src/server.py", "data/cache/x.json"]))

    assert len(tasks[0].rubric) == 1
    assert tasks[0].rubric[0].evidence == "src/server.py"
    assert any("src/router.py" in d for d in tasks[0].dropped)


def test_a_directory_prefix_counts_as_evidence() -> None:
    payload = json.dumps({"tasks": [{
        "category": "execution_flow", "title": "t", "prompt": "p",
        "rubric": [{"criterion": "mentions the cache", "evidence": "data/cache"}],
    }]})
    tasks = parse_proposals(payload, digest_for(["data/cache/move_x.json"]))
    assert len(tasks[0].rubric) == 1


def test_a_task_whose_whole_rubric_was_invented_is_refused() -> None:
    payload = json.dumps({"tasks": [{
        "category": "architecture", "title": "t", "prompt": "p",
        "rubric": [{"criterion": "names the router", "evidence": "src/router.py"}],
    }]})
    with pytest.raises(SuggestionError, match="rubric grounding"):
        parse_proposals(payload, digest_for(["src/server.py"]))


def test_unknown_categories_are_refused() -> None:
    payload = json.dumps({"tasks": [{
        "category": "vibes", "title": "t", "prompt": "p",
        "rubric": [{"criterion": "c", "evidence": "src/server.py"}],
    }]})
    with pytest.raises(SuggestionError):
        parse_proposals(payload, digest_for(["src/server.py"]))


def test_junk_does_not_crash_the_parser() -> None:
    with pytest.raises(SuggestionError):
        parse_proposals(json.dumps({"tasks": "not-a-list"}), digest_for(["a.py"]))


# --- the instruction the agent actually receives ----------------------------


def test_the_prompt_tells_the_agent_to_read_the_repository() -> None:
    """Both harnesses answered from priors and invented modules while sitting in
    a 270-file checkout, because the instruction never said to look at it and
    its only file-related imperative was a prohibition."""
    from app.tasks.propose import ANSWER_INSTRUCTION

    lowered = ANSWER_INSTRUCTION.lower()
    assert "read this repository" in lowered
    assert "must exist in this repository" in lowered
    # Reading has to be explicitly permitted, or "do not modify any other file"
    # reads as "do not touch anything".
    assert "reading any file is expected" in lowered
    assert "answer.md" in lowered


def test_the_prompt_does_not_leak_the_rubric() -> None:
    """Telling the agent what it is graded on is teaching to the test — whether
    it goes and looks unprompted is the thing being measured."""
    from app.tasks.propose import ANSWER_INSTRUCTION

    lowered = ANSWER_INSTRUCTION.lower()
    for leak in ("rubric", "criteri", "graded on", "you will be scored"):
        assert leak not in lowered, f"{leak!r} leaks the grading scheme into the prompt"


def test_verdict_survives_a_judge_that_returns_junk_types() -> None:
    v = parse_verdict(json.dumps({"criteria": "nope", "invented": 7}), RUBRIC)
    assert v.score == 0.0
    assert len(v.missing) == 3
    assert v.invented == []
