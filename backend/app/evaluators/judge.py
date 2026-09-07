"""Grade a comprehension answer against a rubric, grounded and blind.

Two rules hold this together, and dropping either turns the score back into a
number that means nothing:

**Grounded.** The judge is given the repository's real file tree alongside the
answer, and every rubric criterion already cites a path that was verified to
exist when the rubric was written. So the judge checks claims instead of
admiring prose, and a fluent answer that names modules the repo does not
contain is caught by `invented` — which is a lookup, not an opinion.

**Blind.** The judge is never told which harness or model produced the answer.
The whole product exists to rank harnesses; a judge that knows which one it is
reading is not measuring them.

The judge is NOT deterministic — gpt-5.x rejects temperature=0 (Known Defect
#17) — so a single score is noisy. Run repetitions and compare distributions,
not one number against another. `aggregate.py` already flags anything under
three repetitions as statistically weak.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ModelProvider
from app.repositories.suggest import SuggestionError, _extract_json

SYSTEM = """You grade an answer written about a codebase, against a fixed rubric.

Reply with ONE JSON object and nothing else:
{
  "criteria": [{"criterion": "<copied verbatim>",
                "verdict": "met" | "partial" | "missed",
                "note": "one short sentence of evidence from the answer"}],
  "invented": ["module or file the answer names that is not in the file tree"],
  "rationale": "two sentences, what the answer got right and what it missed"
}

Rules:
- Judge ONLY against the rubric criteria you are given. Do not invent new ones.
- When SOURCE OF CITED FILES is present, check the answer's claims against it.
  A claim that contradicts the source is "missed", however confidently it is
  written and however well it reads. Plausibility is not correctness.
- Where a criterion's file is not included, judge that criterion on coverage as
  before, and do not penalise the answer for the omission.
- "met" — the answer states the fact. Different wording is fine; a vague gesture
  in the right direction is not.
- "partial" — the answer gets a substantive part of the criterion right and the
  rest wrong or absent. Use this rather than rounding to met or missed: a
  criterion covering three things, answered correctly for two, is partial.
- "missed" — absent, or wrong.
- Length is not quality. A short answer that satisfies every criterion beats a
  long one that does not.
- For "invented", list only names the answer presents as existing in the repo and
  which do not appear in the file tree. An analogy or a hypothetical is not an
  invention. Be conservative: if unsure, leave it out.
- You are not told who wrote the answer. Do not speculate about it."""


PARTIAL_CREDIT = 0.5


@dataclass
class Verdict:
    score: float | None = None
    met: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    rationale: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "met": self.met,
            "partial": self.partial,
            "missing": self.missing,
            "invented": self.invented,
            "rationale": self.rationale,
            "error": self.error,
        }


_ANSWER_FILE = re.compile(r"^\+\+\+ b/ANSWER\.md$", re.M)


def answer_from_patch(patch: str | None) -> str | None:
    """Pull ANSWER.md's added lines out of the agent's diff.

    Preferred over the harness's own final message because it is identical
    across harnesses and has no length cap — smolagents truncates its final
    message at 4000 characters, which would silently cost an answer marks for
    content it actually wrote.
    """
    if not patch or not _ANSWER_FILE.search(patch):
        return None
    lines: list[str] = []
    inside = False
    for line in patch.splitlines():
        if line.startswith("+++ "):
            inside = line.strip().endswith("b/ANSWER.md")
            continue
        if not inside:
            continue
        if line.startswith("diff --git "):
            break
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    body = "\n".join(lines).strip()
    return body or None


def resolve_answer(patch: str | None, final_message: str | None) -> tuple[str | None, str]:
    """The answer text and where it came from."""
    if (from_file := answer_from_patch(patch)) is not None:
        return from_file, "ANSWER.md"
    if final_message and final_message.strip():
        return final_message.strip(), "final_message"
    return None, "none"


def build_messages(
    question: str,
    rubric: list[dict[str, Any]],
    answer: str,
    tree: list[str],
    evidence: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    criteria = "\n".join(
        f"{i + 1}. {c.get('criterion', '')}  [evidence: {c.get('evidence', '')}]"
        for i, c in enumerate(rubric)
    )
    # The source of the files the rubric cites. Without it the judge holds only
    # paths, so it can confirm an answer covers the right topics and names real
    # files while having no way to tell a correct trace from a confident wrong
    # one. Optional so a repo that cannot be read still grades as it used to.
    source = ""
    if evidence:
        blocks = "\n\n".join(f"--- {path} ---\n{text}" for path, text in evidence.items())
        source = f"\nSOURCE OF CITED FILES:\n{blocks}\n"
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            # Deliberately contains no harness name, model id or run id.
            "content": (
                f"QUESTION ASKED:\n{question}\n\n"
                f"RUBRIC:\n{criteria}\n\n"
                f"REAL FILE TREE ({len(tree)} paths):\n" + "\n".join(tree[:400]) + "\n"
                f"{source}\n"
                f"ANSWER TO GRADE:\n{answer[:24000]}"
            ),
        },
    ]


def parse_verdict(text: str, rubric: list[dict[str, Any]]) -> Verdict:
    raw = _extract_json(text)
    wanted = [str(c.get("criterion", "")) for c in rubric]
    criteria = raw.get("criteria")
    judged = criteria if isinstance(criteria, list) else []

    met: list[str] = []
    partial: list[str] = []
    for item in judged:
        if not isinstance(item, dict):
            continue
        # `met: true` is still honoured so a rubric graded by an older prompt,
        # or a model that ignores the enum, does not silently score zero.
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict not in ("met", "partial") and item.get("met") is not True:
            continue
        bucket = partial if verdict == "partial" else met

        name = str(item.get("criterion", "")).strip()
        # Only credit criteria that were actually in the rubric, so a judge
        # cannot invent a criterion and then award itself the mark.
        match = next((w for w in wanted if w and (w in name or name in w)), None)
        if match and match not in met and match not in partial:
            bucket.append(match)

    missing = [w for w in wanted if w and w not in met and w not in partial]
    raw_invented = raw.get("invented")
    invented = [str(x)[:120] for x in (raw_invented if isinstance(raw_invented, list) else [])][:20]

    # Score is the criteria hit rate, computed HERE from the rubric rather than
    # taken from the model. Asking a model for an overall number invites it to
    # round its own impression up; counting is not negotiable — the model only
    # ever says met/partial/missed per criterion.
    score = (len(met) + PARTIAL_CREDIT * len(partial)) / len(wanted) if wanted else None
    return Verdict(
        score=score,
        met=met,
        partial=partial,
        missing=missing,
        invented=invented,
        rationale=str(raw.get("rationale", ""))[:800],
    )


DIFF_SYSTEM = """You compare a candidate code change against the change that was actually made.

Reply with ONE JSON object and nothing else:
{
  "same_behaviour": true|false,
  "score": 0.0 to 1.0,
  "differences": ["a behavioural difference that matters"],
  "rationale": "two sentences"
}

Rules:
- Judge BEHAVIOUR, not resemblance. Different variable names, a different helper,
  a different file layout, extra error handling — none of these are differences
  if the resulting behaviour matches. Say so.
- Score 1.0 for a change that achieves the same outcome by any means. Score low
  only when the candidate fails to achieve it, or achieves something else.
- A candidate that fixes the problem MORE thoroughly than the reference is not
  wrong. Score it high and note the difference.
- List only differences that would be visible to a caller."""


@dataclass
class DiffVerdict:
    score: float | None = None
    same_behaviour: bool | None = None
    differences: list[str] = field(default_factory=list)
    rationale: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "same_behaviour": self.same_behaviour,
            "differences": self.differences,
            "rationale": self.rationale,
            "error": self.error,
        }


async def judge_diff(
    provider: ModelProvider,
    model_id: str,
    task_title: str,
    agent_patch: str | None,
    reference_diff: str,
) -> DiffVerdict:
    """Score an agent's change against the real commit (ADR-005).

    This metric has a known bias and the ADR records it: a correct fix written
    differently from the original scores low. The prompt pushes hard toward
    behaviour over resemblance to blunt that, but it cannot remove it — which is
    why this averages with the test score rather than replacing it, and why the
    raw comparison is reported alongside the number.
    """
    if not agent_patch or not agent_patch.strip():
        return DiffVerdict(score=0.0, error="no patch to compare")
    try:
        result = await provider.complete(
            model_id,
            [
                {"role": "system", "content": DIFF_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"TASK: {task_title}\n\n"
                        f"--- reference change (what was actually done) ---\n"
                        f"{reference_diff[:12000]}\n\n"
                        f"--- candidate change ---\n{agent_patch[:12000]}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=3000,
        )
        raw = _extract_json(result.content)
        score = raw.get("score")
        return DiffVerdict(
            score=min(1.0, max(0.0, float(score))) if isinstance(score, int | float) else None,
            same_behaviour=raw.get("same_behaviour") is True,
            differences=[str(d)[:200] for d in (raw.get("differences") or [])][:10],
            rationale=str(raw.get("rationale", ""))[:800],
        )
    except SuggestionError as exc:
        return DiffVerdict(error=f"judge returned unusable output: {exc}")
    except Exception as exc:  # noqa: BLE001 - a judging failure must not lose the run
        return DiffVerdict(error=f"{type(exc).__name__}: {exc}"[:300])


async def judge_answer(
    provider: ModelProvider,
    model_id: str,
    question: str,
    rubric: list[dict[str, Any]],
    answer: str | None,
    tree: list[str],
    evidence: dict[str, str] | None = None,
) -> Verdict:
    """Score one answer. Never raises: a judging failure is recorded, not fatal."""
    if not answer:
        return Verdict(score=0.0, missing=[str(c.get("criterion", "")) for c in rubric],
                       error="the run produced no answer to grade")
    if not rubric:
        return Verdict(error="no rubric stored for this task; nothing to grade against")
    try:
        result = await provider.complete(
            model_id,
            build_messages(question, rubric, answer, tree, evidence),
            temperature=0.0,
            max_tokens=4000,
        )
        return parse_verdict(result.content, rubric)
    except SuggestionError as exc:
        return Verdict(error=f"judge returned unusable output: {exc}")
    except Exception as exc:  # noqa: BLE001 - a judging failure must not lose the run
        return Verdict(error=f"{type(exc).__name__}: {exc}"[:300])
