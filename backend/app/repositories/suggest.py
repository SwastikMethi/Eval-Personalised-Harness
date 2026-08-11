"""AI-assisted setup: infer build/test commands and nominate benchmark commits.

The regex detectors in `detectors.py` cover Python and JS/TS only, and cannot
read a README. A model can — so its output is offered as a *suggestion*, never
applied. The user edits it, saves it, and the baseline then proves empirically
whether the commands work. The model guesses; the baseline verifies.

Nothing here is trusted: a missing field stays missing rather than being
invented, and malformed output returns an error instead of raising.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ModelProvider
from app.repositories.digest import Digest

COMMAND_FIELDS = ("install", "build", "test", "lint", "typecheck")

SYSTEM = """You analyse a source repository and report how to build and test it.

Reply with ONE JSON object and nothing else:
{
  "commands": {"install": str|null, "build": str|null, "test": str|null,
               "lint": str|null, "typecheck": str|null, "test_framework": str|null},
  "rationale": {"<command name>": "one short sentence citing the file you used"},
  "confidence": "high" | "low",
  "commits": [{"sha": str, "why": "one short sentence"}]
}

Rules:
- Use null for a command the project genuinely does not have. Most Python
  projects have no build or typecheck step; inventing one is worse than null.
- Commands must run from the repository root, non-interactively.
- test_framework is the runner whose OUTPUT FORMAT applies: pytest, vitest,
  jest, go, cargo, unittest.
- For "commits", pick from the supplied list only. Prefer commits that fix a
  behavioural bug AND touch tests, because those grade well. Avoid docs,
  formatting, dependency bumps and merges. At most 5. Use the exact sha given.
- Never guess a command you cannot support from a file you were shown."""


@dataclass
class Suggestion:
    commands: dict[str, str | None] = field(default_factory=dict)
    test_framework: str | None = None
    rationale: dict[str, str] = field(default_factory=dict)
    confidence: str = "low"
    commits: list[dict[str, str]] = field(default_factory=list)
    model_id: str = ""


class SuggestionError(Exception):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose or ```json fences often enough to expect it."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    if not fenced:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise SuggestionError("model did not return JSON")
        candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise SuggestionError(f"model returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SuggestionError("model returned JSON that is not an object")
    return parsed


def parse_suggestion(text: str, model_id: str, known_shas: set[str]) -> Suggestion:
    raw = _extract_json(text)
    commands_raw = raw.get("commands")
    commands_raw = commands_raw if isinstance(commands_raw, dict) else {}

    commands: dict[str, str | None] = {}
    for name in COMMAND_FIELDS:
        value = commands_raw.get(name)
        # Anything that is not a usable string becomes absent, not invented.
        commands[name] = value.strip() if isinstance(value, str) and value.strip() else None

    framework = commands_raw.get("test_framework")
    rationale = raw.get("rationale")
    commits_raw = raw.get("commits")

    commits: list[dict[str, str]] = []
    for entry in commits_raw if isinstance(commits_raw, list) else []:
        if not isinstance(entry, dict):
            continue
        sha = str(entry.get("sha", "")).strip()
        # Only shas we actually supplied — a hallucinated one cannot be replayed.
        match = next((k for k in known_shas if k.startswith(sha) or sha.startswith(k)), None)
        if sha and match:
            commits.append({"sha": match, "why": str(entry.get("why", ""))[:200]})

    return Suggestion(
        commands=commands,
        test_framework=(
            framework.strip() if isinstance(framework, str) and framework.strip() else None
        ),
        rationale={
            str(k): str(v)[:200]
            for k, v in (rationale.items() if isinstance(rationale, dict) else [])
        },
        confidence="high" if raw.get("confidence") == "high" else "low",
        commits=commits[:5],
        model_id=model_id,
    )


def build_messages(digest: Digest, detected: dict[str, Any]) -> list[dict[str, Any]]:
    """Detector output goes in as a hint — the model corrects it, not repeats it."""
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Static detection found (may be wrong or incomplete):\n"
                f"{json.dumps(detected, indent=2)}\n\n"
                f"{digest.as_prompt_text()}"
            ),
        },
    ]


async def suggest_setup(
    provider: ModelProvider,
    model_id: str,
    digest: Digest,
    detected: dict[str, Any],
) -> Suggestion:
    result = await provider.complete(
        model_id, build_messages(digest, detected), temperature=0.0, max_tokens=1200
    )
    known = {c["sha"] for c in digest.commits}
    return parse_suggestion(result.content, model_id, known)
