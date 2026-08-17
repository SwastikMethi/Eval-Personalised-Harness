"""Propose comprehension tasks, and the rubric that will grade them.

Every attempt to score this product's agents on *code* has been blocked by the
repository's test infrastructure rather than by the agents: unfailable tests, a
runner missing from the graded container, generated tests that could not be
verified. A question like "trace the execution flow of the move lookup" needs
none of that, and still measures the thing a coding harness is for — finding
its way around an unfamiliar codebase and reasoning about it correctly.

The rubric is written HERE, at proposal time, by the same model call that
writes the question and with the same repository digest in front of it. That
matters for two reasons: the criteria are concrete and checkable rather than
vibes, and BOTH harnesses are then graded against the identical rubric, which
is what makes the comparison a comparison.

Each criterion cites a path as its evidence, and any criterion whose evidence
does not exist in the real file tree is dropped before the rubric is stored. A
hallucinated rubric would otherwise score every answer wrong with total
confidence.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.providers.base import ModelProvider
from app.repositories.digest import Digest
from app.repositories.suggest import SuggestionError, _extract_json

CATEGORIES = ("architecture", "execution_flow", "feature_plan")

# Appended to every proposed prompt.
#
# The first version said only "write your answer to ANSWER.md, do not modify any
# other file" — and both harnesses answered from priors, in two and three model
# calls, inventing modules like `src/handlers/battle_handler.py` while sitting in
# a 270-file checkout of the real code. Nothing told them to read it, and the one
# file-related imperative was a prohibition, which frames the job as writing
# rather than exploring. A comprehension benchmark that never says "go and look"
# measures what the model already believed about repositories in general.
#
# The rubric stays OUT of this. Telling an agent what it will be graded on is
# teaching to the test, and whether it goes and looks unprompted is the thing
# being measured.
ANSWER_INSTRUCTION = (
    "\n\nBefore answering, read this repository. Your answer must describe THIS "
    "codebase — open the files, follow the calls, and check what the code actually "
    "does rather than what a project like this usually does.\n\n"
    "Every file, module, class and function you name must exist in this repository. "
    "Naming something that does not exist here counts against the answer.\n\n"
    # Citation is cheap to ask for and expensive to fake, so it pushes an agent
    # to open files without hinting at what the rubric wants. Measured runs
    # stopped after three or four commands and answered from the file layout.
    "Cite the file each claim comes from, inline, like (src/server.py). A claim "
    "with no source behind it is worth less than one you checked.\n\n"
    "Reading any file is expected."
    # HOW the answer is delivered is deliberately absent. It used to be here —
    # "write ANSWER.md" — which fixed mini-SWE-agent's shell convention at
    # task-creation time, before any harness was known, and a smolagents
    # CodeAgent then reported writing a file it never wrote. The adapter
    # appends its own idiom at run time: see DELIVER_AS_FILE and
    # DELIVER_AS_FINAL_ANSWER in harnesses/base.py.
)

SYSTEM = """You design comprehension tasks that measure how well a coding agent
understands an unfamiliar repository.

Reply with ONE JSON object and nothing else:
{
  "tasks": [
    {
      "category": "architecture" | "execution_flow" | "feature_plan",
      "title": "short label",
      "prompt": "what the agent is asked to do, 1-3 sentences",
      "rubric": [
        {"criterion": "a specific fact a correct answer must contain",
         "depth": "structural" | "behavioural" | "deep",
         "evidence": "the path in this repo that proves it"}
      ]
    }
  ]
}

Rules:
- Propose one task per category, three in total.
- Questions must be answerable from THIS repository and specific to it. "Describe
  the architecture" is worthless; "explain how a move lookup reaches the cache and
  what happens on a miss" is a question with a right answer.
- Every criterion must be checkable by reading the repo — a named module, a real
  function, an actual call order, a genuine dependency. Never a matter of taste,
  never "explains clearly", never "is well structured".
- `evidence` must be a path that appears in the file tree you were given. If you
  cannot cite one, leave the criterion out.
- 6 criteria per task, spread evenly across the three depths — roughly two of each:
    structural  — answerable from the file tree plus one file: which module owns a
                  thing, what the entry point is, where something is registered.
    behavioural — needs one file read properly: what a function returns, what
                  happens on a cache miss, what the default is.
    deep        — needs following calls between files: exact ordering, tie-breaks,
                  how a value reaches its final shape.
  A rubric of six deep criteria cannot tell a careful shallow answer from an
  invented one — they both score zero. The spread is what makes the score mean
  something.
- One criterion, one fact. "Explains damage AND type effectiveness AND status
  handling" is three criteria wearing a coat, and it scores zero for an answer
  that got two of them right.
- feature_plan asks for a PLAN, not an implementation: which files change, in what
  order, and what could break.
- Keep execution_flow to ONE flow through at most three modules. A question
  spanning the whole system takes more file reads than an agent will spend, so it
  measures patience rather than comprehension."""


DEPTHS = ("structural", "behavioural", "deep")


@dataclass
class Criterion:
    criterion: str
    evidence: str
    # How much reading this criterion costs. Carried through to the report so a
    # low score can be read properly: all-structural-met is "skimmed and was
    # honest", all-missed is "did not look".
    depth: str = "deep"


@dataclass
class ProposedTask:
    category: str
    title: str
    prompt: str
    rubric: list[Criterion] = field(default_factory=list)
    # Criteria dropped because their evidence path is not in the repo. Surfaced
    # rather than silently removed: a proposer that invents paths is a fact
    # about the model worth seeing.
    dropped: list[str] = field(default_factory=list)


def _tree_paths(digest: Digest) -> set[str]:
    return {p.strip().lstrip("./") for p in digest.tree if p.strip()}


def _evidence_exists(evidence: str, paths: set[str]) -> bool:
    """True when the cited path is a real file or a real directory prefix."""
    cited = evidence.strip().lstrip("./").split(":")[0].strip()
    if not cited:
        return False
    return any(p == cited or p.startswith(cited.rstrip("/") + "/") for p in paths)


def parse_proposals(text: str, digest: Digest) -> list[ProposedTask]:
    raw = _extract_json(text)
    paths = _tree_paths(digest)
    tasks: list[ProposedTask] = []

    entries = raw.get("tasks")
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        category = str(entry.get("category", "")).strip()
        title = str(entry.get("title", "")).strip()
        prompt = str(entry.get("prompt", "")).strip()
        if category not in CATEGORIES or not title or not prompt:
            continue

        kept: list[Criterion] = []
        dropped: list[str] = []
        items = entry.get("rubric")
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            text_of = str(item.get("criterion", "")).strip()
            evidence = str(item.get("evidence", "")).strip()
            depth = str(item.get("depth", "")).strip().lower()
            if not text_of:
                continue
            if evidence and _evidence_exists(evidence, paths):
                kept.append(
                    Criterion(
                        criterion=text_of[:400],
                        evidence=evidence[:200],
                        # Unlabelled counts as deep: assuming the hardest tier is
                        # the reading that does not flatter the agent.
                        depth=depth if depth in DEPTHS else "deep",
                    )
                )
            else:
                dropped.append(f"{text_of[:120]} (cited {evidence[:80] or 'nothing'})")

        # A task whose every criterion was invented cannot grade anything.
        if kept:
            tasks.append(
                ProposedTask(
                    category=category,
                    title=title[:200],
                    prompt=prompt[:4000],
                    rubric=kept[:7],
                    dropped=dropped,
                )
            )

    if not tasks:
        raise SuggestionError("no proposed task survived rubric grounding")
    return tasks


async def propose_tasks(
    provider: ModelProvider, model_id: str, digest: Digest
) -> list[ProposedTask]:
    result = await provider.complete(
        model_id,
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": digest.as_prompt_text()},
        ],
        temperature=0.0,
        max_tokens=6000,
    )
    return parse_proposals(result.content, digest)


# --- rubric storage ----------------------------------------------------------
# File-backed for the same reason as repair.fixup_path: `make migrate` is
# broken, so a new column is not available. ponytail: move to a column when
# migrations work — this is one JSON blob per task either way.


def rubric_path(task_id: str) -> Path:
    return settings.data_dir.resolve() / "rubrics" / f"{task_id}.json"


def save_task_meta(task_id: str, data: dict[str, Any]) -> Path:
    """Whatever grading this task later needs, merged into one file per task.

    A theory task stores its rubric here; a commit task stores the reference
    diff ADR-005 scores against. Same store because it is the same question —
    "what does the grader need that the task row cannot hold".
    """
    path = rubric_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_task_meta(task_id) or {}
    path.write_text(json.dumps({**existing, **data}, indent=2))
    return path


def save_rubric(task_id: str, task: ProposedTask) -> Path:
    return save_task_meta(task_id, asdict(task))


def load_task_meta(task_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(rubric_path(task_id).read_text())  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return None


# Kept as the name the judge path reads; a rubric is just one kind of metadata.
load_rubric = load_task_meta
