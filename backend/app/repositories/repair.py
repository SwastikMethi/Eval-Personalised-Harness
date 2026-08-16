"""Make a repo's own test suite runnable, without fixing the bug for the agent.

`baseline.py` already installs a missing runner inside the container and reports
what the repo ought to add. That fixes "pytest is not installed"; it does not
fix `pytest-asyncio` missing for `async def` tests, or a test file with a bug of
its own. Those leave the suite producing no usable signal, and a benchmark then
grades every agent against silence.

The dangerous version of this feature repairs `src/` — which deletes the bug the
agent is being asked to fix, so every harness scores full marks on a task that no
longer exists. The allowlist below is therefore enforced on the returned diff,
not requested in the prompt: a model cannot be trusted to stay inside a boundary
that decides whether the benchmark measures anything.

The resulting patch is applied to BOTH the agent's workspace and the graded
tree. If those ever diverge, every score is meaningless.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.providers.base import ModelProvider
from app.tasks.historical import is_test_file

# Files that configure how tests RUN. None of them can contain the behaviour
# under test, which is what makes them safe to rewrite.
ALLOWED_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "pytest.ini",
        "tox.ini",
        "conftest.py",
        "package.json",
        "package-lock.json",
    }
)
_REQUIREMENTS = re.compile(r"^requirements[\w.-]*\.(txt|in)$")

SYSTEM = """You make a repository's existing test suite runnable. You do NOT fix its bugs.

Reply with ONE unified diff in a ```diff fenced block, and nothing else.

You may ONLY change:
- requirements*.txt / requirements*.in, pyproject.toml, setup.cfg, setup.py
- pytest.ini, tox.ini, conftest.py, package.json
- existing test files

You may NOT change application source. If the only way to make a test pass is to
change application code, leave that test failing — a failing test is a valid
baseline, and changing the source would destroy the benchmark.

Typical fixes: add a missing test dependency (pytest, pytest-asyncio), set
asyncio_mode in a config file, correct a test that forgets to await a coroutine,
remove an import of something that never existed.

If nothing in the allowed set would help, reply with exactly: NO_SAFE_REPAIR"""

NO_REPAIR_SENTINEL = "NO_SAFE_REPAIR"

_FENCE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.S)


class RepairError(Exception):
    """The model returned nothing usable, or something outside the allowlist."""


@dataclass
class RepairOutcome:
    patch: str = ""
    applied: bool = False
    reason: str = ""
    # Failing-test counts before and after, so "it helped" is measured.
    before_failures: int = 0
    after_failures: int = 0
    changed_paths: list[str] = field(default_factory=list)


def _strip_prefix(path: str) -> str:
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[2:]
    return path


def patched_paths(diff: str) -> list[str]:
    """Every path a diff claims to touch, from both the header and the hunks."""
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            paths.update(_strip_prefix(p) for p in parts[2:4])
        elif line.startswith(("+++ ", "--- ")):
            candidate = line[4:].strip().split("\t")[0]
            if candidate and candidate != "/dev/null":
                paths.add(_strip_prefix(candidate))
    return sorted(paths)


def _is_allowed(path: str) -> bool:
    parts = Path(path).parts
    # A diff is untrusted input; `../` in it would write outside the snapshot.
    if not parts or ".." in parts or path.startswith("/"):
        return False
    name = Path(path).name
    if name in ALLOWED_NAMES or _REQUIREMENTS.match(name):
        return True
    return is_test_file(path)


def disallowed_paths(diff: str) -> list[str]:
    """Paths the model must not have touched. Non-empty means reject the lot.

    Rejecting the whole patch rather than filtering hunks out of it: a partly
    applied repair is a tree nobody reviewed, and the failure mode is silent.
    """
    return [p for p in patched_paths(diff) if not _is_allowed(p)]


def extract_diff(text: str) -> str:
    if NO_REPAIR_SENTINEL in text:
        raise RepairError("model reports no safe repair is possible")
    match = _FENCE.search(text)
    body = (match.group(1) if match else text).strip()
    if "diff --git" not in body and not body.startswith("--- "):
        raise RepairError("model did not return a unified diff")
    return body + "\n"


def build_messages(
    baseline_steps: dict[str, Any],
    suggested: list[dict[str, str]],
    files: dict[str, str],
) -> list[dict[str, Any]]:
    test_step = baseline_steps.get("test") or {}
    parts = [
        "The test suite does not produce usable results. Baseline output:",
        "",
        str(test_step.get("output") or "")[-6000:],
        "",
    ]
    if suggested:
        parts += [
            "The baseline runner already noticed these gaps:",
            *(f"  - {s.get('file')}: add {s.get('add')} — {s.get('why')}" for s in suggested),
            "",
        ]
    parts.append("Current contents of the files you are allowed to change:")
    for name, content in files.items():
        parts += ["", f"--- {name} ---", content[:4000]]
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n".join(parts)},
    ]


def collect_repairable_files(root: Path) -> dict[str, str]:
    """Read the allowlisted files that exist, so the model edits real content."""
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = str(path.relative_to(root))
        if not _is_allowed(rel):
            continue
        try:
            found[rel] = path.read_text(errors="replace")
        except OSError:
            continue
        if len(found) >= 12:  # a suite this large does not need more context
            break
    return found


def apply_patch(workspace: Path, patch: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=workspace,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0, proc.stderr[:500]


# --- persistence -------------------------------------------------------------
# File-backed rather than a column because `make migrate` is broken (see the
# vault's Known Defects). ponytail: move to a RepositoryCommand column when
# migrations work — the shape is one string per repository either way.


def fixup_path(repo_id: str) -> Path:
    return settings.data_dir.resolve() / "repos" / f"{repo_id}.fixup.patch"


def save_fixup(repo_id: str, patch: str) -> Path:
    path = fixup_path(repo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(patch)
    return path


def load_fixup(repo_id: str) -> str | None:
    path = fixup_path(repo_id)
    try:
        content = path.read_text()
    except OSError:
        return None
    return content or None


def apply_fixup(workspace: Path, repo_id: str) -> bool:
    """Apply a repo's saved test-environment repair to a fresh snapshot.

    Called from BOTH the agent's workspace preparation and the grading
    snapshot. Skipping it in one place and not the other gives the agent a
    different tree from the one its patch is graded in, which invalidates every
    score without failing anything.
    """
    patch = load_fixup(repo_id)
    if not patch:
        return False
    ok, _ = apply_patch(workspace, patch)
    return ok


async def propose_repair(
    provider: ModelProvider,
    model_id: str,
    root: Path,
    baseline_steps: dict[str, Any],
    suggested: list[dict[str, str]],
) -> str:
    """One model call. Returns a diff that has passed the allowlist, or raises."""
    files = collect_repairable_files(root)
    result = await provider.complete(
        model_id,
        build_messages(baseline_steps, suggested, files),
        temperature=0.0,
        max_tokens=2000,
    )
    diff = extract_diff(result.content)
    if bad := disallowed_paths(diff):
        raise RepairError(f"patch touches files outside the allowed set: {bad}")
    return diff
