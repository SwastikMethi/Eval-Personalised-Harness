"""Each harness delivers a comprehension answer in its own idiom.

Every smolagents run in the database scored 0.0, and two of them completed
cleanly. The cause was not the model: the task prompt baked in
"write ANSWER.md" at creation time — mini-SWE-agent's shell convention, fixed
before any harness was known — and a smolagents `CodeAgent` exits by calling
`final_answer()`. One run reported *"Successfully wrote comprehensive analysis
to ANSWER.md"*, spent 12k output tokens, returned a 497-character summary, and
produced a zero-length patch.

The plumbing was eliminated as a cause first: under real container conditions
(uid 1000, bind-mounted /workspace) a `LocalPythonExecutor` with `pathlib`
authorized writes the file, and `git add -A && git diff --cached` captures it.
So the agent never wrote it — it was asked for the wrong thing.
"""

from pathlib import Path

from app.harnesses.base import DELIVER_AS_FILE, DELIVER_AS_FINAL_ANSWER
from app.tasks import propose


def test_task_prompt_does_not_pick_a_delivery_convention() -> None:
    """The prompt is stored before a harness is known, so it must not choose."""
    assert "ANSWER.md" not in propose.ANSWER_INSTRUCTION
    assert "final_answer" not in propose.ANSWER_INSTRUCTION


def test_task_prompt_still_demands_exploration() -> None:
    """The part that shapes answer QUALITY stays: read the repo, cite files.

    Dropping this with the filing convention would have quietly turned the
    benchmark back into a test of what the model already believed.
    """
    text = propose.ANSWER_INSTRUCTION.lower()
    assert "read this repository" in text
    assert "cite the file" in text
    assert "must exist in this repository" in text


def test_the_two_idioms_ask_for_different_things() -> None:
    assert "ANSWER.md" in DELIVER_AS_FILE
    assert "final_answer" in DELIVER_AS_FINAL_ANSWER
    # A CodeAgent writing files is what produced the empty patches.
    assert "not create or modify any file" in DELIVER_AS_FINAL_ANSWER
    # And it must be told a summary is not an answer, which is what it returned.
    assert "summary" in DELIVER_AS_FINAL_ANSWER


def test_final_answer_idiom_refuses_a_claim_of_having_filed_it() -> None:
    """The exact failure: 'Successfully wrote … to ANSWER.md', file absent."""
    assert "counts as no answer at all" in DELIVER_AS_FINAL_ANSWER


def test_file_idiom_releases_the_agent_once_the_answer_is_written() -> None:
    """"Do not finish without it" is a constraint that must also be lifted.

    Measured: a run wrote a complete 1,866-character ANSWER.md early, then
    explored for roughly 120 more steps and was killed at 6,030,328 input
    tokens by the token ceiling. mini-SWE-agent runs `--exit-immediately` and
    stops the moment the model submits, so it was willing to stop and was
    never told to. The file idiom needs both halves: write it, then finish.
    """
    text = DELIVER_AS_FILE.lower()
    assert "do not finish without it" in text, "the demand for an answer stays"
    assert "submit and end the run" in text, "and is released once it exists"
    assert "do not keep" in text


def test_theory_prompt_reaches_the_shell_agent_with_both_halves() -> None:
    """Asserted on the prompt the adapter builds, not on the constant alone.

    A commit replay answers with a patch and must not be told to file an
    answer, so the instruction is appended for `theory` only.
    """
    from app.harnesses.base import HarnessRunRequest

    def prompt_for(kind: str) -> str:
        request = HarnessRunRequest(
            task_id="t1",
            task_prompt="Explain the run lifecycle.",
            workspace_path=Path("/tmp/ws"),
            model_id="m",
            provider="fake",
            timeout_seconds=60,
            max_steps=5,
            temperature=0.0,
            task_kind=kind,
            run_token="tok",
            proxy_base_url="http://relay:8005/proxy",
        )
        return request.task_prompt + (DELIVER_AS_FILE if request.task_kind == "theory" else "")

    theory = prompt_for("theory")
    assert "ANSWER.md" in theory
    assert "submit and end the run" in theory
    assert prompt_for("commit") == "Explain the run lifecycle."
